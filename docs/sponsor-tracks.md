# Sponsor tracks — Cal Hacks 13.0

Reference for choosing which tracks Darwin goes after, so the work gets built into the plan and isn't bolted on at the end. The **fit assessment** is ours. **Track details** is the organizers' text as posted (lightly formatted; it may change, so check the Live Site and Hacker Starter Packs).

Status: **decided Sat Oct 24 ~11:15.** In: Overall/Technical, Microsoft (primary), Anthropic, Factory Droid. Conditional: SpacetimeDB (go/no-go at CP7, 18:00). Out: Hyphenate (treated as finance-only), Cartesia, Meta, SpaceXAI, everything else. The work items and owners are in PLAN.md Part H. The assessment below is what the decision was based on.

## Fit assessment (Darwin as of weekend plan v3)

Darwin, in one line: an engineering-change agent for Onshape. It onboards a parametric part, asks for the engineering inputs it must not guess, optimizes against validated solvers, and writes back a verified, versioned change after human approval.

| Track | Fit | Extra work | Recommendation | Why |
|---|---|---|---|---|
| **Microsoft: Built for the Real World** (grand prize + Customer Impact Award) | Very strong | Low (framing, bench numbers, a customer quote) | **Go: primary** | The criteria (customer understanding, measurable usefulness, path to production, responsible design, end to end) map onto Roadmap v2 almost one-to-one: maturity levels, evidence, approval, recovery. |
| **Hyphenate: The Hyphenated Enterprise** ($8k / $5k / $3k) | Strong on criteria. **Eligibility unclear:** the track is titled "Autonomous Systems for Finance". | Low–medium (a video that opens with "the moment", a seats line, a real-vs-simulated sheet) | **Go if non-finance projects qualify.** Check the full track doc or the booth first. | "Limited access, a clean record of its work, knowing when to ask" matches isolated writes, the evidence report and blocking questions. "The moment" is the FEA catching a failure at a mounting hole, then the repair. "We may try a scenario of our own" matches pasting their own Onshape URL. |
| **Anthropic** ($5k credits + Max) | Good, **if we have a real named community** | Low (one real conversation, plus framing) | **Go if someone talks to a real user today** | We already use Claude for every agent role. A broad "engineers" won't count. It has to be a named group such as collegiate rocketry or FRC robotics teams (heavy Onshape users), and we need their own words. "Know where it could go wrong" is our safety story. |
| **Most Technically Complex / Overall** (general) | Strong | None beyond the plan | **Go (automatic)** | Multi-agent + real CAD + FEA + matched-budget baselines. |
| **Best Hardware Hack** (general, Bambu A1 Mini) | Medium | Low–medium | **Consider** | Printed fins and bracket. Much stronger with a physical load test: hang weights on the printed bracket and compare with the prediction. That also gives Microsoft and Hyphenate their "proof it works". |
| **Factory Droid SDK** ($2k cash), not on our list | Surprisingly good | Medium (4–6 h) | **Consider instead of Cartesia** | Scores well when Droid "runs on a trigger you designed, with thoughtful control over what it can touch, and visible plans, diffs and results". Idea: when onboarding returns "unsupported: no thermal adapter", Droid drafts the adapter as a sandboxed PR. The conformance harness runs on it, and an engineer reviews it; it's never auto-loaded. |
| **SpacetimeDB** ($2,048 / $1,024 / $512) | Possible, but it's a re-architecture | High (6–10 h) | **Only if someone fully owns it** | It must be "the core real-time backend". For us that would mean live run state, agent coordination and a multi-engineer review/approval room, replacing our in-process event bus the night before judging. Our backend is Python. SpacetimeDB modules are Rust or C# (TypeScript support unverified), so the backend would talk to it over HTTP. |
| **Cartesia** (Meta glasses, TBD) | Weak | Medium (3–5 h) | **Skip** | "Voice should be core, not a feature added for the demo." A voice goal box and spoken blocking questions would be a feature. |
| **Meta: Bringing People Closer Together** | Weak | — | **Skip** | It's judged on strengthening human connection, which Darwin doesn't do. |
| **SpaceXAI: Make it Legendary** | Ineligible as built | — | **Skip** | The track exists, but it requires the project to be built with Cursor (we use Claude Code) and the Grok Imagine or Voice API inside the product. Prize: a keyboard. |
| Others (Nessie, CRS, x402, Visa, Bright Data, Apify, Convex, Mana, Notability, Bitdeer, Elastic, Figma, Moss, Armadin, Creao, Fetch.ai, Atlassian) | None or weak | — | Skip | Finance, commerce, scraping or platform-specific. Bitdeer only if free credits appear (one `call_model` branch). |

**Open questions before we commit:**
1. Does Hyphenate accept non-finance projects? Get the full doc linked as "CalHacks_Hyphenate_Track".
2. How many sponsor tracks can one Devpost submission enter?
3. Is sponsor judging at the booths during 10:30–12:30? If so, who leaves the table, and when?

---

## Track details (as posted by the organizers)

### General prizes

| Track | Prize |
|---|---|
| First Overall | MacBook Air 13" M5 |
| Second Overall | Nintendo Switch 2 |
| Third Overall | Google Intelligent Eyewear |
| Most Creative Hack | Instax camera plus film |
| Most Technically Complex Hack | NuPhy Air60 HE |
| Best People-First Hack | Apple Watch SE 3 |
| Best Planet-First Hack | America the Beautiful Parks Pass |
| Best Hardware Hack | Bambu Lab A1 Mini |
| Best Beginner Hack | AirPods 4 |
| Best Solo Hack | AirPods Pro 3 |
| Hacker's Choice | Logitech MX Master 4 |

### Shortlisted sponsor tracks (full criteria)

#### Grand Prize: Built for the Real World (Microsoft) · also Microsoft Customer Impact Award
**Challenge:** Build a production-minded AI agent that solves a meaningful problem in finance, productivity, healthcare, or another high-impact domain.
**Judging criteria:** customer understanding · measurable usefulness · path from prototype to production · responsible design · end-to-end functionality.
**Prizes:**
- Grand Prize: a Microsoft Surface laptop for each member of the winning team; present the project remotely at a Microsoft Delta/Frontier Co. FDE team tech talk; 1:1 mentorship with senior FDEs from the Delta/Frontier Co team.
- Customer Impact Award: present remotely at a Microsoft Delta/Frontier Co. FDE team tech talk; 1:1 mentorship with senior FDEs from the Microsoft Delta team.

#### The Hyphenated Enterprise: Autonomous Systems for Finance (Hyphenate)
Every submission is judged on the same four questions:
1. **Is it real enough?** Realistic data, a messy problem, and proof that it works.
2. **Would you hire it?** For which seats, and would it earn them: limited access, a clean record of its work, and knowing when to ask?
3. **Did we see something new?** A company, problem or approach we haven't seen made autonomous before.
4. **The moment.** When it catches what others missed, recovers from something going wrong, or defends a decision when questioned.

Teams should bring:
- a demo video that opens with their moment
- a live demo at judging (judges may ask them to try a scenario of their own)
- one line on the seats their system fills
- proof it works: what's real, what's simulated, and how they know

More details: "CalHacks_Hyphenate_Track" (linked doc).
**Prizes:** $8000, $5000, $3000 for the top 3 teams; expedited interview process for the top 5 teams.

#### Anthropic
1. **A named community.** "Students" is too broad. "Transfer students at Berkeley trying to find housing" is the right register.
2. **A real problem.** You have lived it, or you talked to someone who has.
3. **It works.** One thing done well and usable on Monday beats a broad demo.
4. **Thoughtful use of Claude.** Claude does something that matters to the solution, and you know where it could go wrong for the people using it.

**Prize:** $5,000 in Claude credits + 1 year of Claude Max 20x + Office Hours.

#### Best Use of Factory Droid SDK (Factory)
**Eligibility:** The project must use the Droid SDK (TypeScript or Python) in a meaningful way. Droid should do real work in the running product, not just help you write code. The repo README should explain where and how Droid is used.

**What scores well:**
- Droid runs on a trigger you designed, like an event, a schedule, a user action, or another agent.
- Thoughtful control over what Droid can touch, with safety built in.
- Making Droid's work visible: plans, steps, diffs, and results.

**What scores poorly:**
- A chatbot wrapper with Droid added on.
- Demos that only work in slides.
- Projects where we can't tell what the agent did.

**Prize:** $2000 cash, Factory credits, and swag.

#### Spacetime (SpacetimeDB)
We'd love to see projects where Spacetime is the core real-time backend, especially anything with live shared state, multiplayer interaction, or instant sync between users, agents or systems. That makes it a great fit not just for games, but also for chat/community apps, collaborative tools, social experiences, AI agent coordination, live dashboards, trading or financial-style apps, auctions and marketplaces, shared simulations, multiplayer productivity tools, and stream/creator tools. SpacetimeDB's docs position it around real-time subscriptions, transactional updates, and server-side logic running close to the data, which is why these kinds of apps fit well.

We'd be excited by something like a real-time portfolio sim, prediction market, collaborative trading game, shared ops dashboard, multi-user planning tool, or AI systems coordinating in a persistent world state. The main thing we'd want is for SpacetimeDB to be meaningfully used, not just added on the side.

Examples built with or around Spacetime: BitCraft Online / BitCraftPublic, Elegon, Pogly (a real-time collaborative stream overlay), the official chat app tutorials/templates, a video chat app.

**Prizes:** 1st $2,048 · 2nd $1,024 · 3rd $512.

#### Best Use of Cartesia (Cartesia)
Build a useful voice experience with Cartesia. Voice should be core to the product, not just a feature added for the demo. Other tools are fine; make clear what Cartesia contributes.

**What to submit:**
- a working demo
- a 2-minute, demo-first presentation: one complete user flow, then a brief problem + how you built it
- a short README: setup, Cartesia features used, known limitations
- source access for judges (per event rules); no API keys or secrets in the repo

**Judging criteria (25% each):**
- **Problem and originality:** useful, clearly scoped, thoughtfully designed?
- **Use of Cartesia:** meaningfully integrated into the core experience? Voice clear, responsive and natural?
- **Execution:** main flow works? Likely edge cases handled?
- **Impact and responsibility:** accessibility, privacy and responsible use considered?

We'll favor a strong working prototype over a large unfinished idea.

**Ideas:**
- Commute standup: a voice-only morning brief you can interrupt while driving (hands busy)
- Ambient / wearable assistant: help without pulling out a phone
- Keep-your-voice accessibility: a clone for reading aloud or speaking another language
- Live coach or translator: low-latency back-and-forth where voice quality matters
- Multi-speaker agent: tutor, debate partner or support sim with distinct voices

Docs: https://docs.cartesia.ai · Playground: https://play.cartesia.ai
**Prize:** Meta glasses (still TBD).

#### Meta/Facebook: Bringing People Closer Together with AI (Meta Inc)
Projects will be judged on how meaningfully they strengthen human connection, how essential and well-integrated AI is, originality, and the strength of the working demo.
**Prize:** an invitation to advance to the Round 2 Hackathon hosted at Meta's Menlo Park campus (travel and accommodations provided; advancement subject to eligibility verification and compliance with Meta's Round 2 Official Rules); Meta swag bag.

#### Make it Legendary with SpaceXAI (SpaceXAI)
Space gives you more to work with than almost any other field. You have access to enormous public datasets, decades of missions, and a literature no human can read all of. Real space data goes in and a legendary project comes out.

To be eligible, your project must be built with Cursor. The more you use Cursor, the more likely you are to win. You must also use the Grok Imagine or Voice API in your project. Bonus points if you use Grok Bot for project planning and team collaboration.
**Prize:** custom Cursor mechanical keyboard.

### Other sponsor tracks (summary)

| Track | Criteria (summary) | Prize |
|---|---|---|
| Best Use of Notability | Notes show how the idea evolved (process, detail, use of handwriting/audio/diagrams/PDFs/Smart Notes, real role in the build) | 1 yr Notability Pro + merch |
| Best Use of Nessie (Capital One) | Completeness, creativity, complexity | $300 Giftogram per person |
| Best Use of Fetch.ai | https://www.fetch.ai/events/calhacks-13-0 | $1500 / $1000 / $500 |
| Best Security Hack (Armadin) | Coming soon | Apple headphones (possibly hacking tools) |
| Best Use of x402 (Coinbase) | Track doc (Google Drive link on the Live Site); two tracks | $500 USDC + recruiter call per member per track (up to $4000) |
| Creao AI: Best AI-First Disruptor / Best One-Person Company / Best Team Empowerment | https://community.creao.ai/CalHacks2026 | $5000 total across the tracks + CREAO Launchpad |
| CRS Financial Intelligence Challenge | Meaningful use of the CRS sandbox, shown live: use of CRS, working demo, usefulness, creativity. Sub-prizes: Best Overall, Best Financial AI Agent, Best Identity/Fraud Innovation, Most Unexpected Use | $1,000 / $500 / interviews |
| Best Use of Bitdeer AI Model Studio | Working project using Model Studio. Innovation 30 %, technical 30 %, use of Model Studio 20 %, impact/presentation 20 % | $500 credits + mice / $200 credits + LEGO |
| Figma | TBD (doc on the Live Site) | Amazon gift cards + recruiting session |
| Best Use of Moss | Voice AI, personal agent, or social post (engagement) | AirPods Max/Pro |
| Best Use of Convex | Reactive TypeScript backend (database, functions, workflow, sync, search, storage) | $5,000 |
| Best Use of Apify / Best Actor | Meaningful use of Apify; best actor built for the event | $2,000 / $1,000 / $800 / $400 / $400; actor $400 |
| Elastic | Coming soon | Meta Quest 3S / Bose QC |
| Reimagining Shopping (Visa) | Innovation 25 %, UX 25 %, technical 20 %, commerce impact 15 %, trust 15 % | $5,000 |
| Atlassian Agentic Workforce Challenge | Doc on the Live Site | AirPods Max |
| Bright Data | Live public web data essential to the product; real sites, no mocks; disqualified for scraping behind login/paywall | $1500+$500 / $1000+$350 / $500+$250 |
| Mana.space | Meaningful use of Mana while building (30 %), usefulness, originality, execution; public Mana links; bonus if it lives in Mana | $5,000 |
