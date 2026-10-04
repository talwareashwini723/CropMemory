# CropMemory MVP
Problem -> Evidence -> Decision -> Outcome -> Memory

## Run (2 minutes)
    pip install -r requirements.txt
    uvicorn app:app --reload
    open http://127.0.0.1:8000

## Optional AI mode
    export ANTHROPIC_API_KEY=your_key   # Windows: set ANTHROPIC_API_KEY=your_key
Without a key the app runs in **offline mode** (rule-based insight from the same evidence) - safe for demos.

## 90-second demo
1. Click **Demo: Tomato** -> **Find evidence** (show Trusted sources / Farmer experiences / Insight)
2. Click a decision -> fill the outcome -> **Add to CropMemory** (counter goes up)
3. Click **Find evidence** again -> new case appears with **NEW** badge = the loop closed
Reset data before the demo: `curl -X POST http://127.0.0.1:8000/api/reset`

## Note
Cases and advisories in `data/` are illustrative sample data. Replace with verified ICAR / SAU / KVK content before real use.
