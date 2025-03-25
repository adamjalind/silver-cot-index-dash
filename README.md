# Silver COT Index Dashboard

A web-based dashboard to visualize the Commitments of Traders (COT) Index for Silver futures, using CFTC data and silver prices via Yahoo Finance.

https://cot-index-for-silver-non-commercial.onrender.com/

## Features
- Automatically fetches and caches COT and silver price data
- Updates data no more than every 4 hours to minimize API usage
- Interactive Dash app with plotly visuals
- Clear layout with Silver price, COT Index and Net Position

## Project Structure
- `app.py`: The main Dash application
- `data/`: Folder for storing cached datasets and timestamps
- `requirements.txt`: Python dependencies

## Getting Started
Install dependencies:
```bash
pip install -r requirements.txt
```

Then run the app:
```bash
python app.py
```

## Deployment
This project is ready to be deployed on [Render.com](https://render.com), Railway, or other platforms that support Python web apps.

You can optionally create a `render.yaml` for automated setup.

---
