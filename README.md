## binance_imbalance_notification

This bot watches the Binance order book.

It compares buy volume and sell volume  
near the current price.

When buying pressure becomes much stronger  
than selling pressure, an alert is sent.

### Planned Improvements

- Create classes (for scalability)
- Add a database (save state after restart)
- Add command `/status`
- Use cloud deployment with Docker and webhooks
- Add logistic regression to predict trend

### Where It Can Be Used

- Scalping strategy
- Exit / take-profit signal
- Price direction prediction
- Probability-based model signals
