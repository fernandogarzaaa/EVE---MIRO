Static Reality Check UI. Keep this `index.html` in sync with
`src/eve_miro/api/static/index.html` — FastAPI serves whichever exists
(`apps/dashboard` first, then package static).

Five views: World, Simulation, Experience, Reality Check, Reliability.
One-click **Load demo** calls `POST /demo`.
