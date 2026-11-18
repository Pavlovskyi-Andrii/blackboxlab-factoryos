# Product and media models: base rates, unit economics, and an honest read on MyCast (as of 2026-11-17/18)

Method note. Every fact below came from WebSearch extracts (24 searches). The session proxy blocks WebFetch for every host except github.com, raw.githubusercontent.com and pypi.org, so no vendor page was opened in full. Facts are labelled "search extract of <URL>". Where the search tool reported conflicting figures I list both. Repository facts about MyCast come from the sibling notes file `repo_state_evidence.md` (same folder), not from the web.

## Key claims

| # | Claim | Source URL | Date/version | Confidence |
|---|---|---|---|---|
| 1 | TrustMRR snapshot of 10,646 listed startups by revenue in the last 30 days: $0 for 5,845 (55%), under $1k for 3,744 (35%), $1k–10k for 816 (7.7%), $10k–100k for 217 (2.0%), over $100k for 24 (0.2%). About 9.9% make ≥$1k/month and 2.3% make ≥$10k/month. | https://x.com/marclou/status/2121974507544183216 | tallied 2026-11-15 | reported_secondary (the platform owner's own tally, read from a search extract; self-selected listings) |
| 2 | Stripe Atlas 2025: 20% of startups charged a first customer within 30 days of incorporation (8% in 2020). Among startups that monetise within 3 months, median time to first payment was 34 days. For solo founders, median first-6-month revenue fell 23% YoY while the top decile rose 19%. | https://stripe.com/blog/stripe-atlas-startups-in-2025-year-in-review ; https://stripe.com/blog/top-solo-founder-traits | 2025 cohort, published 2026 | verified_primary (Stripe's own data, search extract; Atlas-only sample) |
| 3 | Portfolio hit rate. Pieter Levels: 4 of 70+ projects "made money and grew" (≈5%). Marc Lou: 23 projects before his hit. | https://trends.vc/micro-app-portfolios-report-5-hit-rate-vibe-coded-exits-portfolio-os/ | Levels tweet 2021-11-07; report 2026-03-11 | reported_secondary |
| 4 | The vibe-coding supply shock: new App Store submissions in Q1 2026 were about 235,800, up 84% YoY (Sensor Tower data). Apple has blocked or pulled several vibe-coding apps. | https://thenextweb.com/news/vibe-coding-apple-app-store-surge-crackdown | Q1 2026, reported 2026-04 | reported_secondary |
| 5 | Spotify "Personal Podcasts" (beta): generates private AI episodes from a prompt, files, links, email and calendar ("daily briefs"). It can be scheduled daily or weekly. It rolled out to eligible **US Premium** users with monthly credits, and users can buy more. | https://support.spotify.com/us/article/personal-podcasts/ ; https://newsroom.spotify.com/2026-05-21/investor-day-podcast-features-updates/ | launched May 2026 | verified_primary (search extract) |
| 6 | Huxe, built by ex-NotebookLM founders with about $4.6M raised and a near-identical concept (personal daily audio briefings and on-demand "DeepCast"), announced its shutdown on 2026-05-21, one day after Spotify's launch. Service ended 2026-05-28. In October 2026 Apple took a non-exclusive licence to its IP and offered jobs to some staff. | https://techcrunch.com/2026/05/22/audio-generation-app-huxe-founded-by-former-notebooklm-developers-shuts-down/ ; https://appleinsider.com/articles/26/10/09/huxes-ai-tools-for-creating-podcasts-from-a-prompt-is-bought-by-apple | 2026-05-22; 2026-10-09 | reported_secondary |
| 7 | NotebookLM is now branded "Gemini Notebook". Audio Overview quotas run from 3/day at the lowest tier through 6, 20 and 100 to 200/day. The plan columns were ambiguous in the extract. | https://support.google.com/notebooklm/answer/16206866?hl=en | 2026-11 | verified_primary (search extract; tier mapping not confirmed) |
| 8 | Gemini 3.8 Flash TTS costs $9.00 per 1M audio output tokens until 2026-12-31 and **$18.00 from 2027-01-01**, with batch at half price. Flash-Lite TTS is $6 → $12. Google counts 25 audio tokens per second, so standard Flash costs $0.0135/min now and $0.027/min in 2027. Forum users report 32 tokens/s in practice. | https://ai.google.dev/gemini-api/docs/pricing ; https://discuss.ai.google.dev/t/how-many-tokens-are-actually-used-per-second-for-flash-3-8-tts/184714 | 2026-11 | verified_primary (pricing, search extract); anecdotal (32 tok/s) |
| 9 | A daily 10-minute personal episode costs about **$1.35–$4.05 per user per month** in Gemini TTS today, rising to $2.70–$8.10 in 2027. The same episode costs $10.80–$21.60 on ElevenLabs API list prices, and about $4.50 on OpenAI gpt-4o-mini-tts by a forum estimate (that model is marked deprecated). | derived from #8; https://elevenlabs.io/pricing/api ; https://developers.openai.com/api/docs/models/gpt-4o-mini-tts | 2026-11 | inference |
| 10 | beehiiv "State of Paid Newsletters 2026" puts the **median free-to-paid conversion at 0.62%**, with top finance newsletters at 18–20%. | https://www.beehiiv.com/blog/the-state-of-paid-newsletters-2026 | 2026 | vendor_claim |
| 11 | Paid newsletter growth through beehiiv Boosts costs an average of $1.63 per verified subscriber (preliminary early-access data), within a $1–5 range. beehiiv takes a 20% fee, and paid recommendations require the Lite/Pro paid plans. | https://www.beehiiv.com/boosts-promo ; https://www.beehiiv.com/support/article/14492963616279-growing-your-audience-with-beehiiv-boosts | 2026 | vendor_claim |
| 12 | AI search is cutting traffic to small publishers. Chartbeat data via the Reuters Institute: Google search referrals to 2,500+ publishers fell about one third in 2025, and **small publishers lost about 60% over two years**. Ahrefs (Feb 2026) measured a 58% CTR drop for the top result when an AI Overview appears. A UPenn/Northeastern field test found AI Mode cuts clicks by 18.8 points. | https://www.searchenginejournal.com/impact-of-ai-overviews-how-publishers-need-to-adapt/556843/ ; https://ppc.land/googles-ai-mode-cuts-clicks-to-websites-by-18-8-points-field-test-finds/ | 2025–2026 | reported_secondary |
| 13 | Zero-fixed-fee payment rails exist. Gumroad charges 10% + 50¢ on direct sales and 30% on Discover sales, and acts as Merchant of Record. Substack keeps 10% of paid revenue on top of Stripe fees. Paddle pays out to Ukraine except Crimea, Donetsk, Kherson, Luhansk and Zaporizhzhia. | https://gumroad.com/pricing ; https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost ; https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle | 2026 | verified_primary (search extracts; Paddle page may be over a year old) |
| 14 | Telegram Stars pays out about $0.013 per Star ($13 per 1,000), with a 1,000-Star minimum and a 21-day hold. Payouts go through Fragment to a TON wallet. Telegram's own docs give the rate only as a client-config value. | https://core.telegram.org/api/stars ; https://adsgram.ai/blog/adsgram/telegram-stars-explained-price-in-usd-how-to-earn-and-withdraw- | 2026 | verified_primary (mechanics); reported_secondary (rate) |
| 15 | Willingness to pay for podcasts is weak. In qualitative research (US/UK/Norway), the Reuters Institute found listeners "reluctant to pay for podcasts with so many free options", and many would switch shows if a paywall went up. I found **no credible retention or WTP data** for AI briefing apps. | https://reutersinstitute.politics.ox.ac.uk/sites/default/files/2026-04/Changing_Shape_of_News_Podcasting.pdf | May 2026 | reported_secondary |

---

## 1. Micro-SaaS base rates, the vibe-coding boom, and distribution

### Takeaway
Most indie products earn nothing. Even on a self-selected "verified revenue" directory, only about 1 in 10 listed products makes ≥$1k a month. Building is now nearly free, which has flooded supply and pushed the bottleneck entirely to distribution and trust.

### Cited findings
- **TrustMRR distribution.** Marc Lou tallied 10,646 startups on 2026-11-15 by revenue in the last 30 days: $0 for 5,845; under $1k for 3,744; $1k–10k for 816; $10k–100k for 217; $100k+ for 24 (search extract of [x.com/marclou](https://x.com/marclou/status/2121974507544183216)). TrustMRR profiles show verified total revenue, 30-day revenue, MRR and customers. A $0 30-day figure does not mean $0 lifetime: one listing shows Revenue (30d) $0 but $920k in total (search extract of [trustmrr.com/category/fintech](https://trustmrr.com/category/fintech), [trustmrr.com/faq](https://trustmrr.com/faq)).
- **Stripe Atlas 2025 cohort.** 20% of startups charged a first customer within 30 days of incorporation, up from 8% in 2020. Median time to first payment, among startups that monetise within 3 months, fell from 38 to 34 days. Median first-6-month revenue rose 39% YoY (10th percentile +18%, 90th percentile +52%). Atlas has allowed payments before an EIN arrives since January 2025, which matters for non-US founders (search extract of [stripe.com/blog/stripe-atlas-startups-in-2025-year-in-review](https://stripe.com/blog/stripe-atlas-startups-in-2025-year-in-review)).
- **Solo founders.** Among solo-founded Atlas startups, median initial 6-month revenue fell 23% YoY in 2025 while the top decile rose 19% (search extract of [stripe.com/blog/top-solo-founder-traits](https://stripe.com/blog/top-solo-founder-traits)). Winners take more and the median solo founder does worse.
- **Portfolio ("many small bets") evidence.** Levels: "Only 4 out of 70+ projects I ever did made money and grew" (tweet of 2021-11-07, quoted by Trends.vc). Trends.vc report #0155 ("Micro-App Portfolios: 5% Hit Rate…", 2026-03-11) says the portfolio reaches about $3.1M ARR with zero employees, profiles Marc Lou (23 projects before the hit) and flags revenue concentration, maintenance overhead, survivorship bias and platform risk (search extract of [trends.vc](https://trends.vc/micro-app-portfolios-report-5-hit-rate-vibe-coded-exits-portfolio-os/)). A DEV Community count of Levels' "list of all my projects" post finds 113 projects, 19 tagged "Failed", and argues the real hit rate is under 10% ([dev.to](https://dev.to/idonthaveapen/failures-behind-a-420kmonth-solo-founder-i-read-all-751-of-pieter-levels-blog-posts-1h3b), search extract).
- **The supply shock.** Sensor Tower data puts Q1 2026 new App Store submissions at about 235,800, +84% YoY. Apple blocked or pulled several vibe-coding apps, including Replit, Vibecode and Anything ([thenextweb.com](https://thenextweb.com/news/vibe-coding-apple-app-store-surge-crackdown), search extract). Other outlets give +60% YoY releases in Q1 and +104% in April 2026, so methods differ ([winbuzzer.com](https://winbuzzer.com/2026/04/07/vibe-coding-app-store-surge-apple-crackdown-xcxwbn/), search extract). No Product Hunt launch-volume data was found.

### Inferences
- A realistic base rate for "an automated MVP reaches ≥$1k/month" is **≤5–10% per product**. Most of those reach it through a founder with an audience, which this founder lacks. Treat 5% as the planning number.
- Cheap code is not an advantage in late 2026: every competitor has it. The scarce resources are distribution, trust (reviews, case studies, a real person behind the product) and access to a niche buyer.

### Gaps
- No independent (non-Stripe, non-TrustMRR) dataset on time to first dollar for indie products. The Indie Hackers survey data was not found in this round.

## 2. First-buyer channels without an audience

### Takeaway
Every launch platform is now saturated with AI-built products and voted on mostly by other makers. Zero-fixed-cost sales rails work (Gumroad, Substack, Paddle, Telegram Stars), but none of them supplies buyers by itself. The only channels with measurable buyer intent are marketplaces where buyers already search (Gumroad Discover, AppSumo, app stores). Those charge 30–100% of first-sale revenue.

### Cited findings
- **Product Hunt (2026), all anecdotal or vendor-blog evidence.** One blog reports an average conversion of 3.1% across 387 tracked launches. Founders report "thousands of visitors… single-digit signups". One 612-upvote launch produced one paying customer, against 91 from an earlier 300-upvote launch. Most upvotes come from other makers, outbound links are nofollow, and a good launch takes an estimated 50–120 hours of preparation (search extracts of [setproduct.com](https://www.setproduct.com/blog/where-to-launch-startup-2026), [agentlaun.ch](https://www.agentlaun.ch/blogs/is-product-hunt-worth-it), [luka.to](https://luka.to/blog/product-hunt-dead-indie-hackers-first-users-2026)). No audited data exists.
- **Gumroad.** 10% + 50¢ per direct sale and 30% via the Discover marketplace. Gumroad is Merchant of Record and handles sales tax worldwide, with no monthly fee (search extract of [gumroad.com/pricing](https://gumroad.com/pricing)). Some older help-centre versions show different fee wording ([help.gumroad.com](https://help.gumroad.com/article/66-gumroads-fees)).
- **AppSumo.** The headline is 95% of revenue from new buyers the partner brings (minus a 5% processing fee) and 70% from returning AppSumo customers. The partner payments policy says the existing-customer share is negotiated. Payment is net 60 end-of-month because of AppSumo's 60-day refund policy, and revenue is calculated after a 10% Plus-member discount and returns (search extracts of [appsumo.com/sell/marketplace](https://appsumo.com/sell/marketplace/), [appsumo.com/partner-terms/payment-policy](https://appsumo.com/partner-terms/payment-policy/)).
- **Paddle (MoR).** Pays out worldwide except sanctioned regions. The unsupported list names Crimea, Donetsk, Kherson, Luhansk and Zaporizhzhia, so the rest of Ukraine is supported. Buyers in the rest of Ukraine can purchase normally (search extract of [paddle.com help](https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle), [sanctions page](https://www.paddle.com/help/legal/sanctions/impact-of-sanctions-on-russia-and-belarus)). The page may be over a year old.
- **Telegram Stars and Mini Apps.** Telegram says it charges "practically no commission" on Stars and that only taxes and payment-system fees apply (June 2024 post, [telegram.org/blog/telegram-stars](https://telegram.org/blog/telegram-stars)). Withdrawals go through Fragment to a TON wallet. The USD value is a client-config value (`stars_usd_withdraw_rate_x1000`) ([core.telegram.org/api/stars](https://core.telegram.org/api/stars)). Third-party guides give about $0.013 per Star, a 1,000-Star minimum and a 21-day hold. Stars bought through Apple or Google may net about $0.009 (search extract of [adsgram.ai](https://adsgram.ai/blog/adsgram/telegram-stars-explained-price-in-usd-how-to-earn-and-withdraw-), [telestars.io](https://telestars.io/blog/telegram-stars)).
- **SEO and programmatic SEO** now face AI answers. See §3: small publishers lost about 60% of Google referrals over two years.

### Inferences
- For a founder in Ukraine with no budget, **Gumroad (Discover at 30%) and Paddle are the verified Merchant-of-Record routes**. Neither needs a fixed fee, so both fit "zero additional spend".
- Telegram Stars is technically the easiest way to take micro-payments inside an existing bot. Payouts arrive as crypto (TON) after 21 days, so tax and legal handling for a Ukrainian sole proprietor needs owner and accountant review. Ticket sizes are tiny: 1,000 Stars ≈ $13 net.
- Product Hunt is worth only a zero-cost listing. Plan for **≤10 signups** from a cold launch.
- AppSumo lifetime deals bring cash but create permanent support liability and a 60-day refund window. Use them only for a product whose marginal cost per user is near zero. That rules out MyCast because of TTS costs.

### Gaps
- Stripe availability for a Ukraine-resident seller, and Gumroad payout support for Ukrainian bank accounts, were not checked in this round.
- No measured conversion data exists for Telegram Mini Apps in the Ukrainian or Eastern European market.

## 3. Niche media, newsletters and information products

### Takeaway
At the median a newsletter monetises slowly: 0.62% of free subscribers convert to paid. Paid growth costs $1.6–4 per subscriber, which is not affordable at zero spend. Organic search, the classic free channel, is shrinking fastest for small publishers. A newsletter is a slow, durable asset, not a fast path to first money.

### Cited findings
- **Conversion.** beehiiv's 2026 report gives a median free-to-paid conversion of 0.62%, with top finance publishers at 18–20%. Vendor blogs claim 2–5% or 5–10% for the "top quartile" (search extract of [beehiiv.com/blog/the-state-of-paid-newsletters-2026](https://www.beehiiv.com/blog/the-state-of-paid-newsletters-2026), [whop.com/blog/newsletter-statistics](https://whop.com/blog/newsletter-statistics/)).
- **Sponsorship CPMs, all vendor blogs.** $20–130 per 1,000 subscribers ([stroby.ai](https://stroby.ai/newsletter-sponsorship-calculator)). $15–40 for general or lifestyle and $40–100+ for B2B, software and finance ([postion.app](https://postion.app/en/blog/newsletter-sponsorship-rates)). A median of about $89 per 1,000 *opens* ([newsletter.app](https://www.newsletter.app/tools/newsletter-ad-spend)). One marketplace reports Q3 2026 rates from $1.22 (lifestyle) to $18.47 (HR) per 1,000 subscribers. These spreads span two orders of magnitude, so treat every number as anecdotal (search extracts).
- **Growth cost.** beehiiv Boosts averaged $1.63 per verified subscriber (preliminary, early access) within a $1–5 range. beehiiv charges a 20% fee and requires the paid Lite/Pro plans (search extract of [beehiiv.com/boosts-promo](https://www.beehiiv.com/boosts-promo), [beehiiv help](https://www.beehiiv.com/support/article/14492963616279-growing-your-audience-with-beehiiv-boosts)).
- **Platform costs.**
  - beehiiv changed its plans in October 2026 (old Scale became Lite, old Max became Pro). Lite is listed at $49/mo billed yearly, and structured data elsewhere shows $59. beehiiv takes 0% of subscription and digital-product revenue beyond Stripe's 2.9% + 30¢. Its pricing page shows an *average* ad-network income of $39/mo on Lite (search extract of [beehiiv.com/pricing](https://www.beehiiv.com/pricing), [beehiiv.com/blog/beehiiv-pricing-2026](https://www.beehiiv.com/blog/beehiiv-pricing-2026)). The free-plan limits after the October change were not confirmed.
  - Substack is free to publish and keeps 10% of paid revenue. Stripe adds 2.9% + $0.30 per US card payment and 0.7% for Billing. Net is about $6.61 on an $8/month subscriber, or about 17% in total fees (search extract of [support.substack.com](https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost), [sparkleon.substack.com](https://sparkleon.substack.com/p/substack-fees-explained-what-you-keep-when-you-go-paid-on-substack)).
  - Ghost pricing was not checked this round.
- **AI search and publisher traffic.**
  - Chartbeat data in the Reuters Institute's 2026 report: Google search referrals to 2,500+ publishers fell by about one third in 2025, with small publishers losing about 60% over two years and large ones about 22%.
  - Ahrefs, February 2026: a 58% decline in top-result CTR when an AI Overview appears, up from 34.5% in April 2025.
  - A UPenn/Northeastern randomised test found AI Mode cuts publisher referrals by 18.8 points. An SSRN study of 2026-04-03 reported a 39.8% cut in outbound organic clicks from AI Overviews.
  - Google disputes these conclusions (search extracts of [searchenginejournal.com](https://www.searchenginejournal.com/impact-of-ai-overviews-how-publishers-need-to-adapt/556843/), [ppc.land](https://ppc.land/googles-ai-mode-cuts-clicks-to-websites-by-18-8-points-field-test-finds/), [techwyse.com](https://www.techwyse.com/news/search-seo/google-ai-mode-reduces-publisher-clicks-study-2026)).
- **AI podcast saturation as a media analogue.** Inception Point AI produces about 3,000 episodes a week across about 5,000 shows at about $1 per episode. It claims breakeven at about 20 listens per episode, assuming a $50 CPM. Its network had 12M lifetime downloads and 400k subscribers, about 69 listens per episode on average. A third-party estimate puts its revenue at about $770k by November 2025. All of these are company claims or press estimates (search extracts of [implicator.ai](https://www.implicator.ai/the-dollar-episode-how-inception-point-ai-turned-podcasting-into-arbitrage/), [podcastnewsdaily.com](https://www.podcastnewsdaily.com/news/who-needs-humans-inception-point-ai-bets-on-1-podcast-model/article_cd86189a-bd70-4649-a65e-232606c04c8a.html)).

### Inferences: worked newsletter arithmetic at zero spend
Assumptions: median 0.62% conversion and $8/month on Substack, netting $6.61.
- 1,000 free subscribers give about 6 paid, or about $40/month **revenue**.
- $1,000/month net from paid subscriptions needs about 151 paid subscribers, or about 24,000 free subscribers at the median rate.
- Buying 24,000 subscribers at $1.63–4 each would cost about $39k–98k. That is impossible under the budget policy, so growth must be organic.
- Sponsorship at 1,000 subscribers, $20–40 CPM and 4 sends a month would bring $80–160/month, *if* a sponsor can be found. At that size, sponsors are rarely found without a marketplace.
- Verdict: a newsletter takes 6–18 months before meaningful money (inference). It should be a distribution asset for other products, not the profit engine.
- Mass-produced AI content: Inception Point shows it monetises only with programmatic ads at very large scale and very low unit cost. It adds to saturation and the "AI slop" backlash, and it is not a fit for a solo founder with a human approval gate on every publication.

### Gaps
- No reliable data on refund rates or conversion for information products (courses, templates, reports) was found in this round. Gumroad and AppSumo fee structures are known, but outcome data is not.
- Ghost (Pro or self-hosted) pricing was not verified.

## 4. AI podcasts and personalised audio (MyCast's market)

### Takeaway
By November 2026 personalised AI audio has been **absorbed by the platforms**. Spotify ships scheduled personal podcasts and daily briefs from email and calendar to US Premium users. Google gives 3+ Audio Overviews a day for free. ElevenReader gives 10 free hours a month. The best-placed independent startup (Huxe) shut down within about a year and was partly absorbed by Apple. A consumer MyCast subscription competes against free features of products users already pay for.

### Cited findings
- **Spotify Personal Podcasts (beta).** Users prompt, upload files or links, or connect email and calendar for daily briefs, then pick a voice and schedule daily or weekly. Episodes are private, with a set number of monthly credits for eligible US Premium users and an option to buy more. Scheduled generations count against the same limits (search extract of [support.spotify.com/us/article/personal-podcasts](https://support.spotify.com/us/article/personal-podcasts/), [newsroom 2026-05-07](https://newsroom.spotify.com/2026-05-07/personal-podcasts-launch/), [newsroom 2026-05-21](https://newsroom.spotify.com/2026-05-21/investor-day-podcast-features-updates/)). A May 2026 TechCrunch report also covers AI Q&A and briefing generation ([techcrunch.com](https://techcrunch.com/2026/05/21/spotify-adds-ai-powered-qa-and-briefing-generation-features-to-podcasts/)). Languages and availability outside the US were not verified.
- **Huxe.** Founded in late 2024 by Raiza Martin, Jason Spielman and Stephen Hughes, all from the NotebookLM team. It offered daily briefings from email, calendar and interests, plus DeepCast on-demand discussions. On 2026-05-21 it was removed from the app stores, service ended on 2026-05-28 and user data was deleted. No reason was given. TechCrunch's retrospective cites larger platforms offering similar experiences. Apple disclosed a non-exclusive IP licence and job offers to the European Commission (search extracts of [techcrunch.com 2026-05-22](https://techcrunch.com/2026/05/22/audio-generation-app-huxe-founded-by-former-notebooklm-developers-shuts-down/), [techcrunch AI graveyard 2026-11-14](https://techcrunch.com/2026/11/14/the-ai-graveyard-a-running-list-of-projects-and-startups-that-didnt-make-it), [appleinsider.com 2026-10-09](https://appleinsider.com/articles/26/10/09/huxes-ai-tools-for-creating-podcasts-from-a-prompt-is-bought-by-apple)). Funding of about $4.6M comes from secondary aggregators ([startupintros.com](https://startupintros.com/orgs/huxe)).
- **Google (NotebookLM, now "Gemini Notebook").** Audio Overview quotas are 3, 6, 20, 100 and 200 per day across plans. The lowest figure is probably the free tier, but the extract did not label the columns. Quotas reset every 24 hours (search extract of [support.google.com/notebooklm/answer/16206866](https://support.google.com/notebooklm/answer/16206866?hl=en), [16213268](https://support.google.com/notebooklm/answer/16213268?hl=en)).
- **ElevenLabs.** ElevenReader has a free plan with 10 hours of text-to-audio a month and an Ultra plan at $11/month or $99/year. GenFM writes the script for free but bills the TTS credits, and Studio docs say GenFM needs a paid subscription. An older blog post said GenFM was free (search extract of [elevenreader.io/pricing](https://elevenreader.io/pricing), [help.elevenlabs.io GenFM cost](https://help.elevenlabs.io/hc/en-us/articles/30725662424849-How-much-does-GenFM-cost), [elevenlabs Studio plans](https://elevenlabs.io/docs/help-center/product/studio/studio/on-what-plans-can-i-use-studio)).
- **Inception Point AI** (mass-produced shows, ad-funded): see §3.
- **Platform policy on AI podcasts.** No official Spotify or Apple podcast-specific AI disclosure rule was found. A vendor blog says AI podcasts are allowed and disclosure in the show description is best practice ([podcastify.io](https://podcastify.io/blog/can-you-publish-ai-podcasts-on-spotify), secondary). Spotify's AI *music* policy (September 2025) uses DDEX disclosure and Spotify's own review ([stability.ai explainer](https://stability.ai/explainers/ai-music-streaming-platform-policy-how-each-service-treats-ai-generated-music), secondary).
- **Willingness to pay and retention.** The Reuters Institute (May 2026, qualitative) found listeners reluctant to pay for podcasts given free options ([PDF](https://reutersinstitute.politics.ox.ac.uk/sites/default/files/2026-04/Changing_Shape_of_News_Podcasting.pdf), search extract). I found **no credible retention or WTP data** for AI briefing apps. The commonly cited "statistics" roundups (e.g. gitnux) give no sources.

### TTS cost per minute and gross margin for a daily personal episode
Assumptions: a 10-minute episode every day (300 min/month); about 900 characters per minute (≈150 wpm), so about 270k characters/month; Google's stated 25 audio tokens per second (1,500 tokens/min). Script-generation LLM cost is excluded because Gemini text prices were not verified this round.

| Engine (price source) | $/min | TTS COGS per user per month (300 min) | From 2027-01-01 |
|---|---|---|---|
| Gemini 3.8 Flash-Lite TTS, batch ($3/1M) | $0.0045 | **$1.35** | $2.70 |
| Gemini 3.8 Flash-Lite TTS, standard ($6/1M) | $0.009 | $2.70 | $5.40 |
| Gemini 3.8 Flash TTS, standard ($9/1M) | $0.0135 | $4.05 | $8.10 |
| …at the 32 tokens/s forum reports instead of 25 | $0.0173 | $5.18 | $10.37 |
| OpenAI gpt-4o-mini-tts (forum estimate; model labelled deprecated) | ~$0.015 | ~$4.50 | n/a |
| ElevenLabs Flash/Turbo ($0.04/1K chars; extract conflicts: $0.05 or $0.022) | ~$0.036 | ~$10.80 | n/a |
| ElevenLabs multilingual ($0.08/1K chars) | ~$0.072 | ~$21.60 | n/a |

Sources: [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing); [Flash-Lite TTS model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts); [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api); [developers.openai.com gpt-4o-mini-tts](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts); [OpenAI forum](https://community.openai.com/t/understanding-gpt-4o-mini-tts-pricing-input-characters-cost/1151816). All are search extracts.

**Margin example (inference).** Price $8/month through Gumroad at 10% + 50¢ leaves about $6.70 after fees. Subtract Gemini Flash TTS at $4.05 (or $8.10 in 2027) and assume $0.30–1.50 for script LLM calls. Gross profit is then about **$1.15–2.35 per user per month today (14–29%)**. At standard Flash in 2027 it turns **negative: −$1.40 before LLM costs, −$1.70 to −$2.90 with them**. Batch Flash-Lite ($1.35, or $2.70 in 2027) restores the margin to about 48–63% today and 31–46% in 2027. A 5-minute episode halves TTS cost. The free tier is not a production basis: forum users report about 100 requests/day hard caps even on paid Tier 1/2 for 3.8 TTS ([discuss.ai.google.dev](https://discuss.ai.google.dev/t/tier-2-project-still-enforcing-tier-1-daily-quota-100-rpd-on-gemini-3-8-tts-models/186987), anecdotal). The repository already records 429 RESOURCE_EXHAUSTED on the shared free key (`repo_state_evidence.md`).

### Gaps
- Whether Spotify Personal Podcasts supports Ukrainian or Russian, or is available outside the US.
- Whether Gemini Notebook has a public API usable for consumer episodes. Not checked; do not automate the consumer UI.
- Any retention curve for personalised daily audio.

## 5. Per-model scorecard

All of this section is inference built on the cited facts above.

| Model | Customer / value | First-buyer channel | Path to first money | CAC at zero spend | Recurring cost | Margin | Automatable share | Main risks | Confirm / kill data |
|---|---|---|---|---|---|---|---|---|---|
| **B2B micro-tool for one niche workflow** (sold to small businesses or professionals) | Saves hours or money on a painful task | Communities where the niche gathers; marketplace listings (Gumroad, app/plugin stores); owner-approved direct messages | Pre-sale or paid pilot within 2–4 weeks | Founder time only; each outreach needs human approval | Hosting already paid (Render/EC2) | 80–95% | Building 80%+; selling 20–40% (needs a human) | No distribution; vibe-coded clones | Confirm: ≥3 paid pre-orders or pilots from ≥30 qualified conversations in 30 days. Kill: 0 payments after 2 iterations |
| **Information products** (templates, reports, prompt packs) on Gumroad | Shortcut or know-how | Gumroad Discover (30% fee), communities | Days to weeks | ~0 | ~0 | 60–90% after fees | 70–90% | Saturated with AI-generated packs; low ticket ($9–49); refunds unknown | Confirm: ≥10 organic sales in 30 days. Kill: <3 |
| **Telegram bot / Mini App with Stars** (UA/EE market) | Convenience inside Telegram | Telegram channels and groups, owner-approved | 2–6 weeks | ~0 | Existing server | High, but small tickets (~$0.013/Star) | 70–90% | Crypto payout via TON; tax handling; platform dependence | Confirm: ≥1,000 Stars (~$13) earned in 30 days from strangers. Kill: below that |
| **Niche newsletter** (owned list) | Curation and expertise | Organic; cross-promotion; Substack network | 6–18 months to meaningful revenue | $1.6–4 per subscriber if paid; organic otherwise | $0 on Substack (10% take) | ~83% net on paid | Writing 60–80%; trust needs a human voice | AI saturation; AI-search traffic loss; median conversion 0.62% | Confirm: 500 organic subscribers in 90 days with ≥40% opens. Kill: <150 |
| **MyCast consumer subscription** | A personal daily audio brief | None proven; competes with Spotify, Google and ElevenReader | Slowest; no billing exists | Unknown; consumer apps usually need paid acquisition | TTS $1.35–8.10 per user per month plus LLM | 14–63% today at $8/month (depending on engine); negative to 46% after the 2027 price change | Production 90%+; acquisition ~0 | Platforms bundle it free; Huxe precedent; quota limits | Confirm: ≥20 strangers pay ≥$5 within 30 days of a pre-sale, and ≥40% of trial users listen ≥4 of 7 days in week 2. Kill: <5 payers |
| **Mass AI content (Inception Point style)** | Ad inventory | Podcast directories | Needs thousands of episodes | ~0 | ~$1 per episode | Depends on CPM and scale | ~100% | AI slop; platform policy; human approval gate on every publication | Not recommended |

### Ranking

| Model | Speed to first payment | Investment | Complexity | Durability | Profit potential |
|---|---|---|---|---|---|
| Information products | 1 (fastest) | 1 (lowest) | 1 (simplest) | 4 | 4 |
| B2B micro-tool / service-backed tool | 2 | 2 | 3 | 2 | **1** |
| Telegram Stars bot | 3 | 1 | 2 | 4 | 5 |
| Newsletter | 5 | 2 | 2 | **1** | 3 |
| MyCast B2C | 5 | 4 (TTS COGS) | 4 | 5 | 5 |

## 6. What a rational 2026 "MVP factory" looks like (inference grounded in §1–§4)

- **Payment-first, honestly.**
  - Every experiment starts with a landing page and a real payment link. Use a refundable pre-order or a paid pilot via Gumroad or Paddle.
  - Show a "fake door" (a feature that doesn't exist yet) only with explicit wording such as "pre-order, ships by <date>, full refund if not delivered".
  - No fake identities, fake reviews or spam. Each outreach or publication batch is approved by a human, per the repository policy.
- **Fixed kill criteria, set before launch.**
  - 14–21 days per experiment.
  - At least 30 qualified human conversations or ≥300 targeted visitors.
  - Kill if there are fewer than 3 payments, or (for content) fewer than 150 subscribers.
  - Never "pivot by adding features" before the first payment.
- **Throughput.** Building costs about nothing. The binding constraints are the owner's approval time and channel access. A solo founder can realistically run **2–4 genuine market tests a month**. More than that means untested launches that nobody sees.
- **Expected hit rate.** At a 5–10% base rate per product, reaching one product at ≥$1k/month is roughly a 40–65% chance after 10 tests (3–5 months) and about 64–88% after 20 tests. This assumes independence and real distribution effort per test; with no distribution it is near 0.
- **Portfolio discipline.** Concentrate on the first product that takes money. Levels' and Marc Lou's portfolios succeed through one or two winners, and maintenance overhead is the documented failure mode (Trends.vc).

## Counter-evidence and caveats

- **Selection bias in TrustMRR.** Listings are self-submitted and require connecting Stripe. Abandoned products that never connected payments are invisible, so the true $0 share across all indie launches is *higher*. On the other hand, products listed for acquisition skew toward ones that once had revenue.
- **Stripe's incentives.** Stripe Atlas data is first-party marketing from a payments company and covers only Atlas-incorporated firms. The 2025 "faster first revenue" trend coexists with the 23% fall in the solo-founder median.
- **Survivorship bias in "many small bets".** The 5% figure comes from famous winners with large audiences built over a decade. Hit rates for audience-less founders are likely lower (inference).
- **The case for MyCast (steelman).**
  - Spotify's feature is US Premium, beta and credit-limited.
  - Google's quotas and ElevenReader target English-first users.
  - A Ukrainian-language or vertical B2B niche (e.g. daily audio briefs for one profession, or white-label briefings for a newsletter or publisher) may not be served by them. I did not verify the language or country availability of the incumbents.
  - The owner's own daily use (16 consecutive scripts, rated 7/10 on one day) is a genuine but n=1 signal.
- **Newsletter numbers are mostly vendor-sourced.** beehiiv, Whop and Stroby have reasons to make newsletters look lucrative, and CPM ranges span 100×. The 0.62% median is from a vendor and is still the most conservative figure.
- **AI-search harm is contested.** Google says AI features keep referral traffic steady and improve click quality, but it has not published verifiable data. The research figures vary by method (18.8 points, 39.8%, 58%).
- **Gemini TTS pricing.** The doubling on 2027-01-01 comes from a search extract of the pricing page and should be re-checked before it is used in a price decision. Gemini 2.5-era TTS models listed at $10/1M may remain available.
- **Single-extract fragility.** Several "facts" rest on one search extract (Huxe and Apple licence, Spotify rollout terms, Telegram rate). None was opened in full because WebFetch is blocked for these hosts.

## Implications for FactoryOS

1. **Stop treating MyCast as the profit engine.**
   - 39 of 45 MVP PRs mention MyCast (`repo_state_evidence.md`), yet it has no billing, no external listener count and a global cap of 10 listener episodes a day.
   - The consumer category was bundled into Spotify Premium and Google's free tier in May 2026, and the best-funded specialist (Huxe) died.
   - Keep MyCast as the owner's personal tool and a demo asset. Allow **one** bounded validation: a 30-day refundable pre-sale in a niche the incumbents demonstrably don't serve (e.g. Ukrainian-language or one professional vertical). Kill it if fewer than 5 strangers pay.
2. **Do not scale MyCast on paid TTS without repricing.**
   - At $8/month, standard Gemini Flash TTS leaves a 14–29% gross margin today and goes negative after the 2027-01-01 price change.
   - Any paid plan must use batch Flash-Lite or short episodes, and needs explicit owner approval because it is a paid API.
   - Free-tier TTS is not a production basis: the repository already records 429 errors on the shared free key, and forum users report about 100/day caps.
3. **Re-aim the MVP factory at payment-first B2B micro-tools and information products, with distribution designed before code.**
   - Each experiment ships a landing page with a real Gumroad or Paddle pre-order link (both zero fixed fee and usable from Ukraine outside the occupied regions).
   - Each experiment ships a channel plan approved by the owner in one batch, and uses the kill criteria in §6.
   - Target 2–4 tests a month and expect about one ≥$1k/month product per 10–20 tests.
4. **Make content a distribution asset for products, not a revenue line.**
   - A newsletter at the 0.62% median needs about 24k free subscribers for $1k/month net. Paid growth ($1.6–4 per subscriber) is ruled out by the budget policy.
   - Use Substack (free, 10% take) or the existing stack rather than a $49+/month beehiiv plan.
   - Measure subscribers and replies, not views.
5. **Use Telegram Stars only as a micro-payment test rail** inside the existing Telegram control surface (e.g. paid MyBrief or MyCast extras). Have the TON payout and Ukrainian tax treatment reviewed by the owner before any real money flows.
6. **Instrument money, not activity.** For every experiment, record visitors, leads, payments, refunds and net profit separately. The repository currently has no payment provider and no external-user numbers, so "first verified external payment" should be the north-star milestone that gates further platform work.

## Sources

All of these were read as **search extracts** (WebSearch). None were opened in full because WebFetch is blocked for these hosts by the session proxy.

- https://x.com/marclou/status/2121974507544183216
- https://trustmrr.com/faq ; https://trustmrr.com/category/fintech
- https://stripe.com/blog/stripe-atlas-startups-in-2025-year-in-review
- https://stripe.com/blog/top-solo-founder-traits
- https://trends.vc/micro-app-portfolios-report-5-hit-rate-vibe-coded-exits-portfolio-os/
- https://dev.to/idonthaveapen/failures-behind-a-420kmonth-solo-founder-i-read-all-751-of-pieter-levels-blog-posts-1h3b
- https://thenextweb.com/news/vibe-coding-apple-app-store-surge-crackdown
- https://winbuzzer.com/2026/04/07/vibe-coding-app-store-surge-apple-crackdown-xcxwbn/
- https://www.setproduct.com/blog/where-to-launch-startup-2026 ; https://www.agentlaun.ch/blogs/is-product-hunt-worth-it ; https://luka.to/blog/product-hunt-dead-indie-hackers-first-users-2026
- https://gumroad.com/pricing ; https://help.gumroad.com/article/66-gumroads-fees
- https://appsumo.com/sell/marketplace/ ; https://appsumo.com/partner-terms/payment-policy/
- https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle ; https://www.paddle.com/help/legal/sanctions/impact-of-sanctions-on-russia-and-belarus
- https://core.telegram.org/api/stars ; https://telegram.org/blog/telegram-stars
- https://adsgram.ai/blog/adsgram/telegram-stars-explained-price-in-usd-how-to-earn-and-withdraw- ; https://telestars.io/blog/telegram-stars
- https://www.beehiiv.com/pricing ; https://www.beehiiv.com/blog/beehiiv-pricing-2026 ; https://www.beehiiv.com/blog/the-state-of-paid-newsletters-2026 ; https://www.beehiiv.com/boosts-promo ; https://www.beehiiv.com/support/article/14492963616279-growing-your-audience-with-beehiiv-boosts
- https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost ; https://sparkleon.substack.com/p/substack-fees-explained-what-you-keep-when-you-go-paid-on-substack
- https://whop.com/blog/newsletter-statistics/ ; https://stroby.ai/newsletter-sponsorship-calculator ; https://postion.app/en/blog/newsletter-sponsorship-rates ; https://www.newsletter.app/tools/newsletter-ad-spend
- https://www.searchenginejournal.com/impact-of-ai-overviews-how-publishers-need-to-adapt/556843/ ; https://ppc.land/googles-ai-mode-cuts-clicks-to-websites-by-18-8-points-field-test-finds/ ; https://www.techwyse.com/news/search-seo/google-ai-mode-reduces-publisher-clicks-study-2026
- https://www.implicator.ai/the-dollar-episode-how-inception-point-ai-turned-podcasting-into-arbitrage/ ; https://www.podcastnewsdaily.com/news/who-needs-humans-inception-point-ai-bets-on-1-podcast-model/article_cd86189a-bd70-4649-a65e-232606c04c8a.html
- https://support.spotify.com/us/article/personal-podcasts/ ; https://newsroom.spotify.com/2026-05-07/personal-podcasts-launch/ ; https://newsroom.spotify.com/2026-05-21/investor-day-podcast-features-updates/ ; https://techcrunch.com/2026/05/21/spotify-adds-ai-powered-qa-and-briefing-generation-features-to-podcasts/
- https://techcrunch.com/2026/05/22/audio-generation-app-huxe-founded-by-former-notebooklm-developers-shuts-down/ ; https://techcrunch.com/2026/11/14/the-ai-graveyard-a-running-list-of-projects-and-startups-that-didnt-make-it ; https://appleinsider.com/articles/26/10/09/huxes-ai-tools-for-creating-podcasts-from-a-prompt-is-bought-by-apple ; https://startupintros.com/orgs/huxe
- https://support.google.com/notebooklm/answer/16206866?hl=en ; https://support.google.com/notebooklm/answer/16213268?hl=en
- https://elevenreader.io/pricing ; https://help.elevenlabs.io/hc/en-us/articles/30725662424849-How-much-does-GenFM-cost ; https://elevenlabs.io/docs/help-center/product/studio/studio/on-what-plans-can-i-use-studio ; https://elevenlabs.io/pricing/api
- https://ai.google.dev/gemini-api/docs/pricing ; https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts ; https://ai.google.dev/gemini-api/docs/rate-limits
- https://discuss.ai.google.dev/t/how-many-tokens-are-actually-used-per-second-for-flash-3-8-tts/184714 ; https://discuss.ai.google.dev/t/tier-2-project-still-enforcing-tier-1-daily-quota-100-rpd-on-gemini-3-8-tts-models/186987
- https://developers.openai.com/api/docs/models/gpt-4o-mini-tts ; https://community.openai.com/t/understanding-gpt-4o-mini-tts-pricing-input-characters-cost/1151816
- https://podcastify.io/blog/can-you-publish-ai-podcasts-on-spotify ; https://stability.ai/explainers/ai-music-streaming-platform-policy-how-each-service-treats-ai-generated-music
- https://reutersinstitute.politics.ox.ac.uk/sites/default/files/2026-04/Changing_Shape_of_News_Podcasting.pdf
