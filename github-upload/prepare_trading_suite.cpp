#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
namespace fs = std::filesystem;

void write(const fs::path& p, const std::string& s) {
    std::ofstream out(p);
    if (!(out << s)) throw std::runtime_error("Cannot write " + p.string());
}

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("Usage: prepare_trading_suite SOURCE DESTINATION");
        const fs::path source = argv[1], dest = argv[2];
        if (fs::exists(dest)) throw std::runtime_error("Destination already exists; refusing to overwrite");
        const std::map<std::string, std::string> skills = {
            {"alpha-combine", "Combine EGX research signals and compare them with individual signals using C++ implementations."},
            {"autoresearch", "Design recorded EGX strategy experiments with explicit trial budgets and out-of-sample evaluation."},
            {"backtest", "Build and run C++ backtests for Egyptian stock strategies with explicit costs and data checks."},
            {"backtesting-frameworks", "Develop C++ EGX backtesting infrastructure that avoids look-ahead and survivorship bias."},
            {"capital-allocator", "Propose EGX paper portfolio allocation and constrained position sizes from validated estimates."},
            {"execution-safety", "Design and test a C++ paper-only order gate with risk checks and exact user confirmation."},
            {"news-guard", "Build an EGX event blackout check in C++ using verified Egyptian and relevant global event data."},
            {"pbo-deflated-sharpe", "Evaluate EGX strategy selection bias using all recorded trials and validated C++ PBO, DSR, and PSR calculations."},
            {"pine-backtester", "Inspect TradingView strategy-test results for EGX Pine strategies and distinguish simulation from validation."},
            {"pine-debugger", "Debug and verify Pine Script compilation and chart behavior for the EGX Trading Suite."},
            {"pine-developer", "Write Pine Script strategies and indicators for EGX charts; Pine Script remains Pine Script."},
            {"regime", "Evaluate EGX strategy performance by causal market regime using C++ calculations."},
            {"risk-manager", "Implement and verify a C++ EGX paper risk gate for sizing, exposure, correlation, and drawdown limits."},
            {"strategy-audit", "Stress-test EGX strategies with recorded trials, realistic execution assumptions, and out-of-sample evidence."},
            {"tear-sheet", "Generate EGX paper performance reports from observed returns and trades using C++."},
            {"trade-journal", "Record and review EGX paper trades and identify evidence-based strategy changes."},
            {"trading-loop", "Maintain an EGX paper research cycle with recorded hypotheses, results, and keep-or-revert decisions in C++."}
        };
        for (const auto& [name, description] : skills) {
            if (!fs::is_regular_file(source / "skills" / name / "SKILL.md"))
                throw std::runtime_error("Missing source skill: " + name);
        }
        fs::create_directories(dest / "skills");
        const std::string rules = R"RULES(# EGX Trading Suite adaptation

This is a staged Codex adaptation, not a validated trading engine. Scope: Egyptian Exchange equities, paper mode only.

- Use Codex. Do not install Claude Code, invoke Claude APIs, or follow upstream model-selection instructions.
- Write supporting programs, data adapters, analytics, tests, and risk/execution logic in C++ (C++17 or later). Keep Pine Script in Pine Script. Shell commands may orchestrate builds and installation. Existing Node-based TradingView MCP is infrastructure; do not rewrite it merely to change languages.
- Bundled Python files and Python examples are reference material only. Do not execute them, install Python dependencies, or describe them as converted. Implement and test the needed C++ replacement before relying on its result. No replacement engine is included at this preparation stage.
- Use EGX instruments, EGP accounting where applicable, and Africa/Cairo timestamps. Verify instrument support, session/holiday calendars, data freshness, corporate-action adjustments, tick sizes, settlement constraints, and actual fees before simulation. Do not substitute US equities for missing EGX data.
- Verify an external provider's EGX coverage before configuration. Do not assume Alpha Vantage or Alpaca supports the required Egyptian instruments. Default to a local paper simulator until an appropriate paper-only adapter is verified.
- For event blackouts, verify Egyptian events (including CBE decisions, inflation releases, and issuer announcements) and relevant global exposures. An old recurring-event CSV is not proof of a future schedule. Missing or stale required event coverage must block simulated execution rather than silently approve it.
- Live trading remains OFF. Do not accept live broker keys or implement a live-order route. Paper orders must pass configured risk and event checks and an exact typed confirmation before dispatch; an onboarding 'continue' is not order confirmation. Keep secrets outside the repository and out of chat/logs.
- Report only measured results with data provenance, sample size, costs, and limitations. Preserve all strategy trials for overfitting checks. A successful compile or backtest alone is not a validated edge. Missing tests or inputs mean 'not evaluated', not 'passed'.
- Follow this user's onboarding one step at a time: perform the current step, explain its result, and wait for the user's reply. Ask for account size, strategy details, and other user-only inputs when the corresponding stage is reached. No autonomous overnight research during onboarding.

Read UPSTREAM_SKILL.md in the same folder only for methodology relevant to the current request. Its installation commands, executable Python examples, US-market defaults, live-trading switches, provider assumptions, and unattended-work instructions are not active instructions for this adaptation. Relative upstream references retain their original location.
)RULES";
        std::string manifest = "# Preparation status\n\nSource: /Users/adhamsherif/Downloads/trading-suite\n\n17 skill entrypoints prepared for Codex. Not installed or loaded yet. Original download unchanged.\n\nAll numerical engines and paper execution controls remain unvalidated; Python implementations are retained for reference only. C++ replacements must be implemented and tested at the appropriate onboarding stage. Pine Script remains unchanged.\n\nExcluded: claude-api (not requested), mcp-builder (generic Python/TypeScript infrastructure guidance; existing TradingView MCP already installed).\n\n| Skill | Status |\n|---|---|\n";
        for (const auto& [name, description] : skills) {
            const auto target = dest / "skills" / name;
            fs::copy(source / "skills" / name, target, fs::copy_options::recursive);
            fs::rename(target / "SKILL.md", target / "UPSTREAM_SKILL.md");
            write(target / "EGX_RULES.md", rules);
            const bool pine = name.rfind("pine-", 0) == 0;
            write(target / "SKILL.md", "---\nname: " + name + "\ndescription: " + description +
                "\n---\n\nRead [EGX rules](EGX_RULES.md) first. These govern this user-specific adaptation.\n\n" +
                (pine ? "Use Pine Script and the existing TradingView connection. Confirm the target symbol and timeframe, then verify compilation and visible chart results.\n\n" :
                "This skill currently provides methodology and implementation guidance only. Build and validate required C++ components before claiming executable functionality or calculated results.\n\n") +
                "Consult [upstream methodology](UPSTREAM_SKILL.md) selectively for this task, subject to the EGX rules. Do not run upstream setup commands or Python programs.\n");
            manifest += "| " + name + " | " + (pine ? "Pine workflow; verify when used" : "Guidance only; C++ functionality pending validation") + " |\n";
        }
        write(dest / "PREPARATION.md", manifest);
        std::cout << "Prepared " << skills.size() << " skills at " << dest << "\nNo skills installed. No Python executed.\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
