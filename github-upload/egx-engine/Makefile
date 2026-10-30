CXX = clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Werror

egx_rank: main.cpp vendor/json.hpp
	$(CXX) $(CXXFLAGS) main.cpp -o egx_rank

egx_backtest: backtest.cpp main.cpp vendor/json.hpp
	$(CXX) $(CXXFLAGS) backtest.cpp -o egx_backtest

test: egx_rank egx_backtest
	./egx_rank test
	./egx_backtest test

.PHONY: test
