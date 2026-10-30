# EGX Trading Suite adaptation

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
