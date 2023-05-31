import numpy as np
import matplotlib.pyplot as plt


def calculate_pnl(strategy, stock_prices):
    if strategy['type'] == 'long' or strategy['type'] == 'short':
        return (stock_prices - strategy['price']) * strategy['position']
    else:
        strike1 = strategy['strike1']
        strike2 = strategy.get('strike2', None)  # Not all strategies will have a 'strike2'
        premium1 = strategy['premium1']
        premium2 = strategy.get('premium2', None)  # Not all strategies will have a 'premium2'
        position = strategy['position']

        if strategy['type'] == 'long call':
            return np.maximum(stock_prices - strike1 - premium1, -premium1) * position
        elif strategy['type'] == 'short call':
            return np.minimum(premium1 - np.maximum(stock_prices - strike1, 0), premium1) * position
        elif strategy['type'] == 'long put':
            return np.maximum(strike1 - stock_prices - premium1, -premium1) * position
        elif strategy['type'] == 'short put':
            return np.minimum(premium1 - np.maximum(strike1 - stock_prices, 0), premium1) * position

        elif strategy['type'] == 'long call spread':  # esta correcto
            max_profit = strike2 - strike1 - premium1 + premium2
            max_loss = -premium1 + premium2
            pnl = np.where(stock_prices <= strike1, max_loss,
                           np.where(stock_prices > strike2, max_profit,
                                    np.where((stock_prices > strike1) & (stock_prices <= strike2),
                                             (stock_prices - strike1 - premium1 + premium2) * position, 0)))
        elif strategy['type'] == 'short call spread': # esta correcto
            max_profit = premium1 - premium2
            max_loss = (strike2 - strike1 - max_profit)
            pnl = np.where(stock_prices <= strike1, max_profit,
                           np.where(stock_prices > strike2, max_loss,
                                    np.where((stock_prices > strike1) & (stock_prices <= strike2),
                                             ((strike1 - stock_prices + premium1 - premium2)) * position, 0)))
        elif strategy['type'] == 'long put spread':  # esta correcto
            max_profit = strike2 - strike1 + premium1 - premium2
            max_loss = premium1 - premium2
            pnl = np.where(stock_prices <= strike1, max_profit,
                           np.where(stock_prices > strike2, max_loss,
                                    np.where((stock_prices > strike1) & (stock_prices <= strike2),
                                             (strike2 - stock_prices + premium1 - premium2) * position, 0)))

        elif strategy['type'] == 'short put spread': # esta correcto
            max_profit = - premium1 + premium2
            print(max_profit)
            max_loss = -(strike2 - strike1 + premium1 - premium2)
            print(max_loss)
            pnl = np.where(stock_prices >= strike2, max_profit,
                           np.where(stock_prices < strike1, max_loss,
                                    np.where((stock_prices < strike2) & (stock_prices >= strike1),
                                             (-strike2 + stock_prices - premium1 + premium2) * position, 0)))

        else:
            raise ValueError(f"Strategy type {strategy['type']} not recognized.")

        return pnl.astype(np.float64)  # Ensure pnl is float64 to match total_pnl


strategies = []
while True:
    strategy_type = input(
        "Introduce el tipo de estrategia (long, short, long call, short call, long put, short put, long call spread, short put spread, short call spread, long put spread, long straddle, long strangle, short straddle, short strangle, FIN para terminar): ")
    if strategy_type == 'FIN':
        break
    strategy = {'type': strategy_type}
    if strategy_type in ['long', 'short']:
        strategy['price'] = float(input("Introduce el precio de compra o venta: "))
        strategy['position'] = float(input("Introduce la posición (1 para larga, -1 para corta): "))
    elif strategy_type in ['long call', 'short call', 'long put', 'short put']:
        strategy['strike1'] = float(input("Introduce el precio de ejercicio: "))
        strategy['premium1'] = float(input("Introduce la prima: "))
        strategy['position'] = float(input("Introduce la posición (1 para larga, -1 para corta): "))
    elif strategy_type in ['long call spread', 'short put spread', 'short call spread', 'long put spread']:
        strategy['strike1'] = float(input("Introduce el precio de ejercicio inferior: "))
        strategy['strike2'] = float(input("Introduce el precio de ejercicio superior: "))
        strategy['premium1'] = float(input("Introduce la prima para el strike inferior: "))
        strategy['premium2'] = float(input("Introduce la prima para el strike superior: "))
        strategy['position'] = float(input("Introduce la posición (1 para larga, -1 para corta): "))
    strategies.append(strategy)

current_stock_price = float(input("Introduce el precio actual del activo subyacente: "))
min_strike = min((strategy.get('strike1', float('inf')) for strategy in strategies if 'strike1' in strategy),
                 default=None)
max_strike = max((strategy.get('strike1', 0) for strategy in strategies if 'strike1' in strategy), default=None)

if min_strike is None or max_strike is None:
    min_strike = max_strike = current_stock_price

stock_prices = np.linspace(0.5 * min_strike, 1.5 * max_strike, 100)

plt.figure(figsize=(10, 6))
total_pnl = np.zeros_like(stock_prices)
for strategy in strategies:
    pnl = calculate_pnl(strategy, stock_prices)
    total_pnl += pnl
    plt.plot(stock_prices, pnl, label=f"{strategy['type']} P&L")
plt.plot(stock_prices, total_pnl, label='Total P&L', linewidth=2.5)
plt.axvline(x=current_stock_price, color='r', linestyle='--', label='Current Stock Price')
plt.xlabel('Precio del Activo Subyacente')
plt.ylabel('P&L')
plt.legend()
plt.grid()
plt.show()

