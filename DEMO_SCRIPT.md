# SafeRoute Nagpur — Demo & Presentation Script

A ready-to-read script for presenting this project — in a viva, hackathon demo, video walkthrough, or portfolio pitch. Each section pairs **what to say** with **what to click**, so you can present live without missing a beat.

Total runtime: roughly 6-8 minutes for the full walkthrough. A condensed "elevator pitch" version is at the bottom for when you only have 60 seconds.

---

## 1. Open with the problem (30 seconds)

> "Every navigation app on your phone optimizes for one thing — getting there fastest. None of them ask the second, equally important question: is this route actually *safe*? For women navigating a city like Nagpur, especially at night, the fastest route and the safest route are often not the same road. SafeRoute Nagpur is built to answer both questions at once, using real crime data instead of guesswork."

**What to show:** Open the app's **Map** tab — let the colored area markers load before saying anything else.

---

## 2. The risk-aware map (45 seconds)

> "Every dot on this map is a real Nagpur neighborhood — 30 of them — color-coded by current computed risk: green is lower risk, yellow is moderate, red is elevated. This isn't guesswork or a hardcoded list — it's computed live from a real dataset of 1,446 crime records, factoring in street lighting, crowd density, time of day, and distance to the nearest police station."

**What to show:** Click a red or yellow dot to open its info popup — point out the risk score and confidence label. Mention the colors update if you change the time of day later in the route panel.

---

## 3. Route recommendation — the core feature (90 seconds)

> "Here's where it matters most. Say I need to go from here to here." *(pick two areas, e.g. Dharampeth to Ajni)* "The app doesn't just show me one path — it computes real alternative routes across the actual Nagpur street network and scores each one for both time and safety exposure."

**What to show:** Select source/destination, hit **Find Safest Route**. Point at the three cards that appear:

> "This is the **fastest** route — shortest time, but it may cross higher-exposure areas. This is the **safest** — lowest average risk, even if it takes a bit longer. And this is the **recommended** route — the system's best balance of both. Notice the numbers: mean risk, peak risk, and how much extra time each option costs you."

If the origin/destination happen to produce identical routes, that's an honest finding worth naming rather than hiding:

> "Sometimes the safest and fastest paths are genuinely the same road — the app tells you that directly instead of pretending there's a difference that doesn't exist."

**Technical credibility line** (optional, for a technical audience):
> "Under the hood, this uses real k-shortest-path search — Yen's algorithm — over the actual OpenStreetMap road network for Nagpur, over 100,000 real street segments. Risk isn't just assigned by neighborhood either — it blends smoothly across the map and factors in the actual road classification, so a quiet residential street and a well-lit main road in the same area aren't scored as identically risky."

---

## 4. Live location & trip tools (60 seconds)

> "You're not limited to picking areas from a list — tap 'Use My Current Location' and the app finds your nearest matched area automatically and routes from your exact GPS position."

**What to show:** Click "Use My Current Location," let it resolve.

> "Once you've got a route, you can start a **trip check-in**. Set how long you expect the trip to take — say, 20 minutes — and the app starts a countdown. If you don't check in as arrived before time runs out, it automatically sends an alert with your last known location. No manual action needed once it's started."

**What to show:** Start a short test trip (1-2 minutes for demo purposes), show the countdown.

> "It also generates a live tracking link you can text to a trusted contact — no login, no app install on their end — they just open the link and watch your location update on a map in real time."

**What to show:** Copy the share link, open it in a new tab to show the tracking page.

---

## 5. SOS and emergency response (60 seconds)

> "If something actually goes wrong, holding this SOS button for 3 seconds triggers an alert — it captures your location, identifies the real nearest police jurisdiction using actual per-area data, and shows a verified direct-dial number where one exists."

**What to show:** Hold the SOS button, let the overlay appear.

> "I want to be upfront about something here, because it matters for a safety feature: we didn't fabricate phone numbers. Where we have an independently verified number for a specific station, we show it. Where we don't, it falls back to the real, verified Nagpur Police headquarters line — never a guessed number. In a real emergency, a wrong number is worse than no number."

> "You can also set a personal emergency contact — a name and phone number — right here in the app." *(click the shield icon in the header)* "If SOS or a missed trip check-in ever triggers, this specific person gets called and texted directly, along with a live tracking link, instead of just a generic default."

---

## 6. Analytics dashboard (30 seconds)

> "None of this is theoretical — it's all built on a real dataset." *(switch to Analytics tab)* "1,446 real crime records across 30 Nagpur areas, broken down by crime type, time of day, and area-by-area risk. This is the same data actually powering the map and the route model — not a separate demo dataset."

---

## 7. Closing / impact statement (30 seconds)

> "What makes this different from a typical class project demo is that every number you saw is real — real crime data, a real trained model with 88.6% accuracy, a real street network, and real police contact information. It's also honest about its limits — where we don't have verified data, the app says so instead of pretending. That's the standard I think a safety tool actually needs to meet."

---

## 60-Second Elevator Pitch (condensed version)

> "Most navigation apps only optimize for speed. SafeRoute Nagpur adds the missing question — is this route safe? — using a real 1,446-record crime dataset covering 30 Nagpur neighborhoods. It computes genuinely different fastest, safest, and recommended routes across the real Nagpur road network, not just relabeled copies of the same path. If something goes wrong, a 3-second SOS hold alerts the real nearest police station with a verified number, or the personal contact you've set. And a trip check-in timer automatically alerts your contact if you don't confirm you've arrived safely — with a live tracking link they can watch in real time. Everything here is built on real data, and it's honest about where that data has gaps instead of hiding them."

---

## Quick reference: feature-to-benefit table

Use this if asked "why does this feature matter" during Q&A.

| Feature | Benefit |
|---|---|
| Risk-colored map (30 real areas) | See danger zones at a glance, not buried in a table |
| Real k-shortest-path routing | Genuinely different route options, not one path with three labels |
| Road-classification risk signal | Distinguishes a dark side street from a well-lit main road in the same neighborhood — the crime dataset alone can't |
| Live location routing | No manual area lookup — route from exactly where you are |
| 3-second SOS hold | Deliberate, hard to trigger by accident, fast enough in a real emergency |
| Verified police numbers (not guessed) | A wrong number in a real emergency is worse than none — this app never fabricates one |
| Trip check-in auto-alert | Works even if you can't act — no need to manually press anything if something happens |
| Live trip-sharing link | Trusted contact can watch in real time, no app install needed on their end |
| Emergency contact override | Alerts go to a specific person you choose, not a generic default |
| Analytics dashboard | Transparency — the same real data driving the model is visible and auditable |

---

## Anticipated questions & honest answers

**"Is this data real?"**
Yes — 1,446 actual crime records across 30 real Nagpur areas, with real coordinates and real police station contacts where verified.

**"Can it actually call the police automatically?"**
No website can silently auto-dial a phone — that's a deliberate browser security restriction, not a limitation of this app specifically. It automates everything up to that point and needs one tap to place the call.

**"What if the police number for my area isn't in your database?"**
It falls back to the verified Nagpur Police HQ number rather than guessing — 13 of 30 areas currently have a specific verified number; the model doesn't currently fabricate ones for the rest.

**"Does this work offline / does it need internet?"**
No — it needs a live connection to the backend server and, for live tracking, active GPS.

**"How accurate is the risk model?"**
R² = 0.886 on real held-out data — meaningfully predictive, not perfect, and it says so rather than overclaiming.
