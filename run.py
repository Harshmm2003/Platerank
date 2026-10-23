"""Start PlateRank:  python run.py   -> opens http://127.0.0.1:8000
(The old Streamlit screen still works as a fallback:  python -m streamlit run app.py)"""
import threading, webbrowser
import uvicorn

PORT = 8000

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    print(f"PlateRank is running at http://127.0.0.1:{PORT}  (press Ctrl+C to stop)")
    uvicorn.run("api:app", host="127.0.0.1", port=PORT, log_level="warning")
