#define EGX_LIBRARY
#include "main.cpp"

struct Bar { long long time; double open,high,low,close,volume; int session; };
struct Settings { int fast=9,slow=21,hold=2; double cash=100000,allocation=.1,slippage=.001,participation=.01; };
double fees(double value) {
    if(value<=0) return 0;
    return 2+value*.001+std::min(value*.0001,5000.)*2
        +std::clamp(value*.00005,1.,250.)+std::min(value*.00005,5000.)+value*.0005;
}
std::vector<Bar> loadBars(const J& record) {
    if(record.at("currency")!="EGP" || record.at("resolution")!="60") throw std::runtime_error("Expected EGP hourly data");
    std::vector<Bar> out; long long previous=0; std::string previousDate; int session=-1;
    for(const auto& b:record.at("bars")) {
        long long t=b.at("time"); const auto d=date(t); if(d>finish) continue;
        if(t<=previous) throw std::runtime_error("Unsorted or duplicate bar timestamps");
        double o=b.at("open"),h=b.at("high"),l=b.at("low"),c=b.at("close"),v=b.at("volume");
        if(!std::isfinite(o)||!std::isfinite(h)||!std::isfinite(l)||!std::isfinite(c)||!std::isfinite(v)||l<=0||v<0||h<l||o<l||o>h||c<l||c>h) throw std::runtime_error("Invalid hourly OHLCV");
        time_t ts=t; tm local{}; localtime_r(&ts,&local);
        if(local.tm_wday==5||local.tm_wday==6) throw std::runtime_error("Unexpected Friday/Saturday candle");
        if(d!=previousDate) {++session;previousDate=d;}
        out.push_back({t,o,h,l,c,v,session}); previous=t;
    }
    if(out.size()<30) throw std::runtime_error("Insufficient hourly history");
    return out;
}
J simulate(const std::vector<Bar>& bars,const Settings& p) {
    if(p.fast<1||p.slow<=p.fast||bars.size()<=size_t(p.slow)||p.cash<=0||p.allocation<=0||p.allocation>1||p.participation<=0||p.slippage<0||p.slippage>=1||p.hold<0) throw std::runtime_error("Invalid simulation settings");
    double cash=p.cash,peak=p.cash,dd=0,paid=0,entryCost=0,fastSum=0,slowSum=0,previousDiff=0;
    long long shares=0; int entrySession=-1,blocked=0,rejected=0; long long entryTime=0; double entryPrice=0;
    bool pendingBuy=false,pendingSell=false,havePrevious=false;
    J trades=J::array(),equity=J::array(),fills=J::array();
    for(size_t i=0;i<bars.size();++i) {
        const auto& b=bars[i];
        // Signals are from the PREVIOUS close. Only the next observed open can fill.
        if(pendingSell && shares>0) {
            if(b.session-entrySession<p.hold) ++blocked;
            else if(i>0 && shares<=std::floor(bars[i-1].volume*p.participation) && bars[i-1].volume>0) {
                double price=b.open*(1-p.slippage),value=shares*price,f=fees(value);
                cash+=value-f;paid+=f;
                trades.push_back({{"entry_time",entryTime},{"exit_time",b.time},{"shares",shares},{"entry_price",entryPrice},{"exit_price",price},{"net_pnl_egp",value-f-entryCost},{"holding_sessions",b.session-entrySession}});
                fills.push_back({{"side","sell"},{"time",b.time},{"shares",shares},{"price",price},{"fee",f}});
                shares=0;pendingSell=false;
            } else ++rejected;
        }
        if(pendingBuy && shares==0 && i>0) {
            double price=b.open*(1+p.slippage);
            long long q=static_cast<long long>(std::floor(std::min(cash*p.allocation/price,bars[i-1].volume*p.participation)));
            while(q>0 && q*price+fees(q*price)>cash*p.allocation) --q;
            if(q>0) {
                double value=q*price,f=fees(value);cash-=value+f;paid+=f;shares=q;
                entryCost=value+f;entryPrice=price;entryTime=b.time;entrySession=b.session;
                fills.push_back({{"side","buy"},{"time",b.time},{"shares",q},{"price",price},{"fee",f}});
            } else ++rejected;
        }
        pendingBuy=false;
        double value=cash+shares*b.close;peak=std::max(peak,value);dd=std::max(dd,1-value/peak);
        equity.push_back({{"time",b.time},{"equity_egp",value},{"cash_egp",cash},{"shares",shares}});
        fastSum+=b.close;slowSum+=b.close;
        if(i>=size_t(p.fast)) fastSum-=bars[i-p.fast].close;
        if(i>=size_t(p.slow)) slowSum-=bars[i-p.slow].close;
        if(i+1>=size_t(p.slow)) {
            double diff=fastSum/p.fast-slowSum/p.slow;
            if(havePrevious) {
                if(previousDiff<=0 && diff>0 && shares==0) pendingBuy=true;
                if(previousDiff>=0 && diff<0 && shares>0) pendingSell=true;
            }
            previousDiff=diff;havePrevious=true;
        }
    }
    double gain=0,loss=0;size_t wins=0;
    for(const auto& t:trades){double pnl=t["net_pnl_egp"];if(pnl>0){++wins;gain+=pnl;}else loss-=pnl;}
    double last=equity.back()["equity_egp"];
    // Benchmark invests the same 10% once, at first possible strategy execution bar.
    const size_t start=std::min<size_t>(p.slow+1,bars.size()-1);
    double bp=bars[start].open*(1+p.slippage);
    long long bq=static_cast<long long>(std::floor(p.cash*p.allocation/bp));
    while(bq>0 && bq*bp+fees(bq*bp)>p.cash*p.allocation)--bq;
    double benchmark=p.cash-bq*bp-fees(bq*bp)+bq*bars.back().close;
    return {{"bars",bars.size()},{"start_date",date(bars.front().time)},{"end_date",date(bars.back().time)},
        {"initial_equity_egp",p.cash},{"ending_mark_to_market_equity_egp",last},{"return_pct",100*(last/p.cash-1)},
        {"max_drawdown_pct",dd*100},{"closed_trades",trades.size()},{"win_rate_pct",trades.empty()?J(nullptr):J(100.*wins/trades.size())},
        {"profit_factor",loss>0?J(gain/loss):J(nullptr)},{"fees_paid_egp",paid},{"open_shares",shares},
        {"open_position_unrealized_pnl_egp",shares?shares*bars.back().close-entryCost:0},
        {"benchmark_10pct_buy_hold_return_pct",100*(benchmark/p.cash-1)},
        {"settlement_delayed_bars",blocked},{"liquidity_rejected_bars",rejected},{"unfilled_signal_at_end",pendingBuy||pendingSell},
        {"sample_warning",trades.size()<30?"Fewer than 30 closed trades: too small for reliable inference":"Selection bias and other limitations still apply"},
        {"trades",trades},{"equity",equity},{"fills",fills}};
}
void captureTop(const fs::path& root) {
    J experiment=readJson(root/"experiment.json"),original=tv({"state"});
    fs::create_directories(root/"data/hourly");
    auto restore=[&](){tv({"pane","symbol","0",original["symbol"]});tv({"timeframe",original["resolution"]});};
    try {
        tv({"timeframe","60"});
        for(const auto& sym:experiment["symbols"]) {
            std::string symbol=sym;
            J before=tv({"state"}),previous=tv({"ohlcv","--count","500"})["bars"];
            tv({"pane","symbol","0",symbol}); J data,state;bool ready=false;
            for(int attempt=0;attempt<8;++attempt) {
                std::this_thread::sleep_for(std::chrono::milliseconds(500));state=tv({"state"});
                if(bare(state["symbol"])!=bare(symbol)||state["resolution"]!="60")continue;
                data=tv({"ohlcv","--count","500"});
                if(data["bars"]==previous && bare(before["symbol"])!=bare(symbol))continue;
                std::this_thread::sleep_for(std::chrono::milliseconds(300));J second=tv({"ohlcv","--count","500"}),after=tv({"state"});
                auto closed=[](const J& b){J out=J::array();for(const auto& v:b)if(date(v["time"])<=finish)out.push_back(v);return out;};
                if(after["symbol"]==state["symbol"]&&after["resolution"]=="60"&&closed(data["bars"])==closed(second["bars"])) {ready=true;break;}
            }
            if(!ready)throw std::runtime_error("Hourly capture did not settle: "+symbol);
            J record={{"symbol",symbol},{"currency","EGP"},{"resolution","60"},{"observed_state",state},{"metadata",tv({"info"})},
                {"retrieved_unix",std::time(nullptr)},{"source","TradingView Desktop through existing MCP CLI; chart adjustments unverified"},{"bars",data["bars"]}};
            auto checked=loadBars(record);save(root/"data/hourly"/(bare(symbol)+".json"),record);
            std::cout<<symbol<<": "<<checked.size()<<" hourly bars through "<<finish<<std::endl;
        }
        restore();
    }catch(...){try{restore();}catch(...){std::cerr<<"Could not restore chart\n";}throw;}
}
void exportBacktest(const fs::path& root) {
    J config=readJson(root/"experiment.json"),results=J::array();Settings p;
    p.fast=config["fast"];p.slow=config["slow"];p.hold=config["minimum_holding_observed_sessions"];
    p.cash=config["initial_cash_egp_per_symbol"];p.allocation=config["allocation_fraction"];
    p.slippage=config["slippage_bps_each_side"].get<double>()/10000;p.participation=config["prior_bar_volume_participation"];
    fs::create_directories(root/"output/backtest");
    for(const auto& sym:config["symbols"]) {
        std::string symbol=sym;J record=readJson(root/"data/hourly"/(bare(symbol)+".json"));
        if(record["symbol"]!=symbol||bare(record["observed_state"]["symbol"])!=bare(symbol))throw std::runtime_error("Hourly symbol mismatch");
        auto bars=loadBars(record);J result=simulate(bars,p);result["symbol"]=symbol;
        save(root/"output/backtest"/(bare(symbol)+".json"),result);
        std::ofstream csv(root/"output/backtest"/(bare(symbol)+"-equity.csv"));csv<<"time,equity_egp,cash_egp,shares\n";
        for(const auto& row:result["equity"])csv<<row["time"]<<','<<row["equity_egp"]<<','<<row["cash_egp"]<<','<<row["shares"]<<'\n';
        std::ofstream trades(root/"output/backtest"/(bare(symbol)+"-trades.csv"));trades<<"entry_time,exit_time,shares,entry_price,exit_price,net_pnl_egp,holding_sessions\n";
        for(const auto& t:result["trades"])trades<<t["entry_time"]<<','<<t["exit_time"]<<','<<t["shares"]<<','<<t["entry_price"]<<','<<t["exit_price"]<<','<<t["net_pnl_egp"]<<','<<t["holding_sessions"]<<'\n';
        result.erase("equity");result.erase("trades");result.erase("fills");results.push_back(result);std::cout<<result.dump()<<'\n';
    }
    save(root/"output/backtest/summary.json",{{"experiment",config},{"results",results},{"edge_verdict","NOT VALIDATED"}});
    std::ofstream log(root/"output/backtest/trials.jsonl",std::ios::app);
    log<<J({{"run_time",std::time(nullptr)},{"config",config},{"results",results}}).dump()<<'\n';
    std::ofstream md(root/"output/backtest/report.md");
    md<<"# C++ hourly SMA 9/21 exploratory backtest\n\nNot validated. Three independent EGP 100,000 accounts; no combined portfolio.\n\n"
      <<"|Stock|Period|Bars|Net account return|Max drawdown|Closed trades|Win rate|\n|---|---|---:|---:|---:|---:|---:|\n"<<std::fixed<<std::setprecision(2);
    for(const auto& r:results)md<<'|'<<r["symbol"].get<std::string>()<<'|'<<r["start_date"].get<std::string>()<<" to "<<r["end_date"].get<std::string>()<<'|'<<r["bars"]<<'|'<<r["return_pct"].get<double>()<<"%|"<<r["max_drawdown_pct"].get<double>()<<"%|"<<r["closed_trades"]<<'|'<<(r["win_rate_pct"].is_null()?"N/A":r["win_rate_pct"].dump()+"%")<<"|\n";
    md<<"\nSignals use closed candles and fills use the next observed open. 10% allocation, whole shares, no leverage or shorts. "
      <<"Buy size and sell eligibility are capped by 1% of the previous bar's volume; this proxy does not prove available opening liquidity. "
      <<"Sells wait for two subsequent observed trading sessions, conservatively avoiding unverified T0/T1 eligibility. "
      <<"Exit orders remain pending until eligible. Open positions are marked to the last close, not artificially liquidated. "
      <<"Drawdown uses hourly closing equity; intrabar losses can be larger.\n\n"
      <<"Costs use the current [Thndr fee schedule](https://support.thndr.app/en/articles/638558-thndr-order-fees), one transaction per fill, "
      <<"plus assumed 10 basis points adverse execution per side. No subscription waivers. This is not a confirmed account fee quote or an exact Pine replication. "
      <<"Effective fill prices are a friction model, not tick-rounded executable orders.\n\n"
      <<"These symbols were selected after observing the October 18–22 winners in a partial alphabetical scan. "
      <<"The historical backtest therefore has selection hindsight and is NOT out-of-sample. Corporate actions, dividend cashflows, "
      <<"complete holiday/session coverage, tick grids, trading halts and opening liquidity have not been independently verified. "
      <<"Current fees are applied across history as an illustrative assumption. Benchmark is 10% buy-and-hold plus cash, "
      <<"with entry fees/slippage and final mark-to-market. No Sharpe annualization or edge pass is claimed. "
      <<"A short sample or low trade count cannot establish an edge.\n\nEquity curves: [ABUK](ABUK.svg), [FIRE](FIRE.svg), [CCAP](CCAP.svg). "
      <<"Raw trades, hourly equity CSVs, and all recorded trials are in this folder. Paper simulation only; no broker orders.\n";
    // Standalone SVG plots generated in C++; common equity scale for comparability.
    double low=p.cash,high=p.cash;
    for(const auto& sym:config["symbols"]) {
        auto dataset=readJson(root/"output/backtest"/(bare(sym)+".json"));
        for(const auto& e:dataset["equity"]){double v=e["equity_egp"];low=std::min(low,v);high=std::max(high,v);}
    }
    double pad=std::max(50.,(high-low)*.1);low-=pad;high+=pad;
    for(const auto& sym:config["symbols"]) {
        std::string ticker=bare(sym);auto data=readJson(root/"output/backtest"/(ticker+".json"));auto points=data["equity"];
        std::ofstream svg(root/"output/backtest"/(ticker+".svg"));
        svg<<"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1000\" height=\"440\" viewBox=\"0 0 1000 440\"><rect width=\"1000\" height=\"440\" fill=\"#fff\"/><g font-family=\"sans-serif\" fill=\"#17223b\"><text x=\"80\" y=\"32\" font-size=\"22\">"<<ticker<<" — SMA 9/21 hourly equity (EGP)</text><text x=\"80\" y=\"58\">Exploratory; selection hindsight; 10% allocation; fees and assumed slippage</text>";
        for(int k=0;k<=4;++k){double y=85+k*65;svg<<"<path d=\"M80 "<<y<<" H960\" stroke=\"#ddd\"/><text x=\"5\" y=\""<<y+5<<"\">"<<std::fixed<<std::setprecision(0)<<high-(high-low)*k/4<<"</text>";}
        svg<<"<polyline fill=\"none\" stroke=\"#087e8b\" stroke-width=\"2\" points=\"";
        for(size_t i=0;i<points.size();++i)svg<<80.+880.*i/(points.size()-1)<<','<<85+260*(high-points[i]["equity_egp"].get<double>())/(high-low)<<' ';
        svg<<"\"/><text x=\"80\" y=\"380\">"<<data["start_date"].get<std::string>()<<"</text><text x=\"860\" y=\"380\">"<<data["end_date"].get<std::string>()<<"</text><text x=\"80\" y=\"415\">Observed hourly bars; overnight/weekend gaps compressed. Open positions marked to close.</text></g></svg>";
    }
}
void backtestTests() {
    auto check=[](bool condition,const char* name){if(!condition)throw std::runtime_error(std::string("Test failed: ")+name);};
    check(std::abs(fees(10000)-20.5)<1e-8,"fee schedule at EGP 10000");
    std::vector<Bar> b;std::vector<double> prices={10,10,9,8,9,12,14,13,9,8,7,12,14,12,9,8,10,13,8,7,10,12,8,7,10,13,9,8,11,13,8,7,9,12,8,7};
    for(size_t i=0;i<prices.size();++i)b.push_back({1700000000+static_cast<long long>(i)*3600,prices[i],prices[i],prices[i],prices[i],1000000,int(i/4)});
    Settings p;p.fast=2;p.slow=3;p.hold=0;auto result=simulate(b,p);
    check(!result["fills"].empty(),"synthetic trades generated");
    check(result["fills"][0]["time"]==b[6].time,"cross at index 5 fills next open index 6");
    check(std::abs(result["fills"][0]["price"].get<double>()-14.014)<1e-9,"adverse entry slippage");
    auto extended=b;extended.back().close=1000;extended.back().high=1000;auto future=simulate(extended,p);
    for(size_t i=0;i<b.size()-1;++i)check(result["equity"][i]==future["equity"][i],"future change cannot alter earlier equity");
    auto zero=b;for(auto& v:zero)v.volume=0;check(simulate(zero,p)["fills"].empty(),"zero volume prevents fills");
    p.hold=2;auto settled=simulate(b,p);for(const auto& t:settled["trades"])check(t["holding_sessions"].get<int>()>=2,"settlement holding delay");
    for(const auto& e:settled["equity"])check(e["cash_egp"].get<double>()>=0,"cash never negative");
    auto constant=b;for(auto& v:constant)v.open=v.high=v.low=v.close=10;
    check(simulate(constant,p)["closed_trades"]==0,"no crossing no trades");
    double reconstructed=p.cash;for(const auto& f:settled["fills"]){double value=f["shares"].get<double>()*f["price"].get<double>();reconstructed+=(f["side"]=="buy"?-value:value)-f["fee"].get<double>();}
    check(std::abs(reconstructed-settled["equity"].back()["cash_egp"].get<double>())<1e-7,"fill ledger reconciles cash");
    std::cout<<"10 backtest checks passed: fees, trades, next-bar timing, slippage, causality, volume, holding delay, cash, flat prices, ledger reconciliation.\n";
}
int main(int argc,char** argv) {
    setenv("TZ","Africa/Cairo",1);tzset();
    try {if(argc==2&&std::string(argv[1])=="test")backtestTests();
        else if(argc==3&&std::string(argv[1])=="capture")captureTop(argv[2]);
        else if(argc==3&&std::string(argv[1])=="run")exportBacktest(argv[2]);
        else throw std::runtime_error("Usage: egx_backtest test | capture ROOT | run ROOT");
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
