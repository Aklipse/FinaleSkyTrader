# FinaleSkyTrader

Streamlit tool for reading Finale Discord `#pop-items` reactions, assigning SKY gods and alliance members, and generating cross-alliance pop-item trade orders.

## Run

```powershell
python -m pip install -r requirements.txt
python -m streamlit run sky_pop_optimizer.py
```

Create a local `.env` file with:

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_pop_items_channel_id
```

## Streamlit Cloud Secrets

In Streamlit Cloud, open the app settings and add these secrets:

```toml
DISCORD_TOKEN = "your_discord_bot_token"
DISCORD_CHANNEL_ID = "your_pop_items_channel_id"
```
