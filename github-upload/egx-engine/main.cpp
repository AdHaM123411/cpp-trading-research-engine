#include "vendor/json.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <map>
#include <poll.h>
#include <set>
#include <spawn.h>
#include <stdexcept>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
using J = nlohmann::json;
namespace fs = std::filesystem;
extern char** environ;
const std::string baseline="2026-10-15", finish="2026-10-22";
const std::set<std::string> sessions={"2026-10-18","2026-10-19","2026-10-20","2026-10-21",finish};
J readJson(const fs::path& p) { std::ifstream f(p); if(!f) throw std::runtime_error("Cannot read "+p.string()); J j; f>>j; return j; }
void save(const fs::path& p,const J& j) { auto tmp=p; tmp+=".tmp"; {std::ofstream f(tmp); if(!(f<<j.dump(2)<<'\n')) throw std::runtime_error("Cannot write "+p.string());} fs::rename(tmp,p); }
std::string date(long long seconds) { time_t t=seconds; tm result{}; if(!localtime_r(&t,&result)) throw std::runtime_error("Invalid timestamp"); char b[20]; strftime(b,sizeof(b),"%Y-%m-%d",&result); return b; }
std::string bare(const std::string& s) { return s.substr(s.find(':')+1); }
std::string run(std::vector<std::string> args) {
    int pipes[2]; if(pipe(pipes)) throw std::runtime_error("pipe failed");
    posix_spawn_file_actions_t actions; posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions,pipes[1],STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions,pipes[0]);
    posix_spawn_file_actions_addclose(&actions,pipes[1]);
    std::vector<char*> argv; for(auto& s:args) argv.push_back(s.data()); argv.push_back(nullptr);
    pid_t pid; int error=posix_spawn(&pid,argv[0],&actions,nullptr,argv.data(),environ);
    posix_spawn_file_actions_destroy(&actions); close(pipes[1]);
    if(error) {close(pipes[0]); throw std::runtime_error("Cannot launch bridge");}
    std::string output; auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(40);
    bool timeout=false;
    for(;;) {
        if(std::chrono::steady_clock::now()>deadline) {timeout=true; kill(pid,SIGKILL); break;}
        pollfd fd{pipes[0],POLLIN,0}; int ready=poll(&fd,1,200);
        if(ready<0) continue;
        if(ready) {char b[8192]; ssize_t n=::read(pipes[0],b,sizeof(b)); if(n<=0) break; output.append(b,n);}
    }
    close(pipes[0]); int status=0; waitpid(pid,&status,0);
    if(timeout || !WIFEXITED(status) || WEXITSTATUS(status)) throw std::runtime_error("Bridge command failed: "+output);
    return output;
}
J tv(std::vector<std::string> args) {
    const std::string home=getenv("HOME");
    args.insert(args.begin(),home+"/.local/share/tradingview-mcp/src/cli/index.js");
    args.insert(args.begin(),home+"/.local/share/node-v24.22.1-darwin-arm64/bin/node");
    J j=J::parse(run(args)); if(!j.value("success",false)) throw std::runtime_error(j.dump()); return j;
}
J assess(const J& record) {
    if(record.at("currency")!="EGP") throw std::runtime_error("Non-EGP listing excluded from EGP universe");
    if(record.at("resolution")!="1D" && record.at("resolution")!="D") throw std::runtime_error("Not daily candles");
    std::map<std::string,J> bars;
    for(const auto& b:record.at("bars")) {
        auto d=date(b.at("time").get<long long>());
        if(d<baseline || d>finish) continue; // Never use the new week's candles.
        if(bars.count(d)) throw std::runtime_error("Duplicate date "+d);
        double o=b.at("open"),h=b.at("high"),l=b.at("low"),c=b.at("close"),v=b.at("volume");
        if(!std::isfinite(o)||!std::isfinite(h)||!std::isfinite(l)||!std::isfinite(c)||!std::isfinite(v)||l<=0||v<0||h<l||o<l||o>h||c<l||c>h)
            throw std::runtime_error("Invalid OHLCV on "+d);
        bars[d]=b;
    }
    if(!bars.count(baseline)) throw std::runtime_error("Missing baseline close "+baseline);
    for(const auto& d:sessions) if(!bars.count(d)) throw std::runtime_error("Missing session "+d);
    if(bars[baseline]["volume"].get<double>()<=0 || bars[finish]["volume"].get<double>()<=0)
        throw std::runtime_error("No reported trading volume on an endpoint");
    double a=bars[baseline]["close"],b=bars[finish]["close"],v=0;
    for(const auto& d:sessions) v+=bars[d]["volume"].get<double>();
    return {{"symbol",record.at("symbol")},{"name",record.at("name")},{"currency","EGP"},
        {"baseline_close",a},{"week_end_close",b},{"price_return_pct",100*(b/a-1)},
        {"week_volume_shares",v},{"session_count",5},{"corporate_actions_verified",false}};
}
void rank(const fs::path& root) {
    J universe=readJson(root/"data/universe.json"), ranked=J::array(), excluded=J::array();
    J collectionStatus=fs::exists(root/"data/collection-status.json")?readJson(root/"data/collection-status.json"):J({{"status","not_recorded"}});
    std::set<std::string> unique;
    if(universe["data"].size()!=universe["totalCount"].get<size_t>()) throw std::runtime_error("Truncated universe");
    for(const auto& item:universe["data"]) {
        const std::string symbol=item["s"]; if(!unique.insert(symbol).second) throw std::runtime_error("Duplicate universe symbol");
        try {
            if(item["d"][2]!="EGP") throw std::runtime_error("Non-EGP listing excluded from EGP universe");
            J record=readJson(root/"data/bars"/(bare(symbol)+".json"));
            if(record.at("symbol")!=symbol) throw std::runtime_error("Mismatched symbol in cache");
            if(record.at("currency")!=item["d"][2]) throw std::runtime_error("Currency mismatch");
            ranked.push_back(assess(record));
        } catch(const std::exception& e) {excluded.push_back({{"symbol",symbol},{"reason",e.what()}});}
    }
    std::sort(ranked.begin(),ranked.end(),[](const J& a,const J& b){double x=a["price_return_pct"],y=b["price_return_pct"]; return x==y ? a["symbol"]<b["symbol"] : x>y;});
    save(root/"output/ranking.json",{{"baseline_date",baseline},{"week_start","2026-10-18"},{"week_end",finish},
        {"universe_count",unique.size()},{"ranked_count",ranked.size()},{"excluded_count",excluded.size()},{"collection_status",collectionStatus},
        {"scope","Current TradingView EGX stock directory; EGP listings only; complete five-session data required"},
        {"limitations","Provisional chart-price returns, not total returns or strategy profits. Corporate actions and historical listing membership not independently verified. Missing listings are excluded, never assigned zero."},
        {"ranking",ranked},{"excluded",excluded}});
    std::ofstream csv(root/"output/ranking.csv"); csv<<"symbol,baseline_close,week_end_close,price_return_pct,week_volume_shares\n";
    for(const auto& r:ranked) csv<<r["symbol"].get<std::string>()<<','<<r["baseline_close"]<<','<<r["week_end_close"]<<','<<r["price_return_pct"]<<','<<r["week_volume_shares"]<<'\n';
    std::ofstream report(root/"output/report.md");
    report<<"# EGX weekly price ranking: October 18–22, 2026\n\n"
          <<"Coverage: "<<collectionStatus.value("coverage","see exclusions")<<". Leaders apply only to the eligible collected subset.\n\n"
          <<"Baseline: October 15 close. Ranked "<<ranked.size()<<" of "<<unique.size()
          <<" directory listings; excluded "<<excluded.size()<<". EGP listings only.\n\n"
          <<"| Symbol | October 15 close (EGP) | October 22 close (EGP) | Price return |\n"
          <<"|---|---:|---:|---:|\n"<<std::fixed<<std::setprecision(2);
    for(size_t i=0;i<std::min<size_t>(10,ranked.size());++i) {
        const auto& r=ranked[i];
        report<<'|'<<r["symbol"].get<std::string>()<<'|'<<r["baseline_close"].get<double>()<<'|'
              <<r["week_end_close"].get<double>()<<'|'<<r["price_return_pct"].get<double>()<<"%|\n";
    }
    report<<"\nThese are provisional historical chart-price returns, not strategy profits or recommendations. "
          <<"Corporate actions and historical listing membership have not been independently verified. "
          <<"No trading costs are deducted. Selecting these winners and backtesting on the same week would introduce selection bias.\n\n"
          <<"See ranking.json for every ranked listing and explicit exclusion reasons. Raw source candles are retained in ../data/bars/. "
          <<"The C++ backtest, risk and execution engines remain separate work; no order was placed.\n";
    if(!csv || !report) throw std::runtime_error("Failed to write ranking exports");
    std::cout<<"Ranked "<<ranked.size()<<" / "<<unique.size()<<" listings; excluded "<<excluded.size()<<"\n";
    for(size_t i=0;i<std::min<size_t>(10,ranked.size());++i) std::cout<<ranked[i].dump()<<'\n';
}
void collect(const fs::path& root,int limit) {
    J universe=readJson(root/"data/universe.json"), original=tv({"state"});
    fs::create_directories(root/"data/bars");
    save(root/"data/original-chart.json",original);
    auto restore=[&](){tv({"pane","symbol","0",original["symbol"]}); tv({"timeframe",original["resolution"]});};
    try {
        tv({"timeframe","1D"});
        int count=0,failures=0; J previous;
        for(const auto& item:universe["data"]) {
            if(limit>0 && count>=limit) break;
            const std::string symbol=item["s"], ticker=bare(symbol);
            if(!std::all_of(ticker.begin(),ticker.end(),[](unsigned char c){return std::isalnum(c)||c=='_'||c=='-';})) throw std::runtime_error("Invalid ticker");
            if(item["d"][2]!="EGP") continue;
            auto file=root/"data/bars"/(ticker+".json");
            if(fs::exists(file)) continue;
            ++count;
            try {
                J before=tv({"state"});
                previous=tv({"ohlcv","--count","30"})["bars"];
                tv({"pane","symbol","0",symbol});
                J data,state; bool matched=false;
                for(int attempt=0;attempt<6;++attempt) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(500));
                    state=tv({"state"});
                    if(bare(state["symbol"])!=ticker || (state["resolution"]!="1D" && state["resolution"]!="D")) continue;
                    data=tv({"ohlcv","--count","30"});
                    if(data["bars"]==previous && bare(before["symbol"])!=ticker) continue;
                    std::this_thread::sleep_for(std::chrono::milliseconds(250));
                    J second=tv({"ohlcv","--count","30"}), after=tv({"state"});
                    // Compare closed candles only: an in-progress candle may change during collection.
                    auto closed=[](const J& bars){J out=J::array();for(const auto& b:bars) if(date(b["time"])<=finish) out.push_back(b);return out;};
                    if(after["symbol"]==state["symbol"] && after["resolution"]==state["resolution"] && closed(second["bars"])==closed(data["bars"])) {matched=true;break;}
                }
                if(!matched) throw std::runtime_error("Chart did not settle on requested symbol and daily data");
                J record={{"symbol",symbol},{"name",item["d"][1]},{"currency",item["d"][2]},
                    {"resolution",state["resolution"]},{"observed_symbol",state["symbol"]},{"retrieved_unix",std::time(nullptr)},
                    {"source","TradingView Desktop via existing MCP bridge"},{"adjustment_basis","Chart setting; corporate actions not independently verified"},{"bars",data["bars"]}};
                save(file,record); failures=0;
                std::cout<<count<<" "<<symbol<<" captured"<<std::endl;
            } catch(const std::exception& e) {
                std::ofstream log(root/"data/collection-errors.jsonl",std::ios::app); log<<J({{"symbol",symbol},{"error",e.what()},{"time",std::time(nullptr)}}).dump()<<'\n';
                std::cout<<count<<" "<<symbol<<" FAILED: "<<e.what()<<std::endl;
                if(++failures>=3) throw std::runtime_error("Three consecutive collection failures; stopping to diagnose");
            }
        }
        restore();
    } catch(...) {try{restore();}catch(const std::exception& e){std::cerr<<"RESTORE FAILED: "<<e.what()<<'\n';}throw;}
    rank(root);
}
void tests() {
    J r={{"symbol","EGX:TEST"},{"name","Test"},{"currency","EGP"},{"resolution","1D"},{"bars",J::array()}};
    auto add=[&](std::string d,double c){tm t{};strptime(d.c_str(),"%Y-%m-%d",&t);t.tm_hour=10;t.tm_isdst=-1;r["bars"].push_back({{"time",mktime(&t)},{"open",c},{"high",c},{"low",c},{"close",c},{"volume",100}});};
    add(baseline,100);for(const auto& d:sessions)add(d,110);add("2026-10-25",999);
    auto require=[](bool b){if(!b)throw std::runtime_error("Test failed");};
    require(std::abs(assess(r)["price_return_pct"].get<double>()-10)<1e-9);
    auto reject=[&](J x){bool failed=false;try{assess(x);}catch(...){failed=true;}require(failed);};
    J x=r;x["bars"].erase(0);reject(x);
    x=r;x["bars"].erase(2);reject(x);
    x=r;x["bars"].push_back(x["bars"][0]);reject(x);
    x=r;x["bars"][0]["close"]=0;reject(x);
    x=r;x["bars"][5]["volume"]=0;reject(x);
    x=r;x["currency"]="USD";reject(x);
    x=r;x["resolution"]="60";reject(x);
    x=r;for(auto& b:x["bars"]) if(date(b["time"])==finish){b["open"]=90;b["high"]=90;b["low"]=90;b["close"]=90;}
    require(std::abs(assess(x)["price_return_pct"].get<double>()+10)<1e-9);
    std::cout<<"9 tests passed: gains, losses, future exclusion, missing endpoints/sessions, duplicate dates, invalid price, zero endpoint volume, currency and timeframe checks.\n";
}
#ifndef EGX_LIBRARY
int main(int argc,char** argv) {
    setenv("TZ","Africa/Cairo",1);tzset();
    try {
        if(argc<2)throw std::runtime_error("Usage: egx_rank test | rank ROOT | collect ROOT [limit]");
        std::string mode=argv[1]; if(mode=="test")tests();
        else if(argc>=3 && mode=="rank")rank(argv[2]);
        else if(argc>=3 && mode=="collect")collect(argv[2],argc>3?std::stoi(argv[3]):0);
        else throw std::runtime_error("Invalid command");
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
#endif
