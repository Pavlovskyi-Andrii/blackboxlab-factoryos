# Economics of an autonomous AI content farm (state as of 17 November 2026)

> **Method limitation - read first.** In this session `WebFetch` failed for every host tried (support.google.com, tubefilter.com, thenextweb.com, air.io, ai.google.dev - all `ENOTFOUND`, i.e. outside the session's allowed network domains), and the shared web-search budget ran out before the last batch of checks. **No page was opened in full.** Every fact below comes from the search tool's extract of the linked page. Where the search was restricted to the official domain (support.google.com, tiktok.com, cloud.google.com / ai.google.dev, developers.google.com) or the extract explicitly quotes the official page (help.openai.com, help.x.com), I label it `verified_primary` *in the weak sense "official page content returned by search; full page not opened"*. Everything else is `reported_secondary` or `vendor_claim`. Numbers that the report will lean on (YPP thresholds, the February 2027 change, Veo prices) should be re-opened on the official page before publication. Items I could not check at all are listed under "Gaps" and are marked "prior knowledge, unverified".

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | YouTube Partner Program (YPP) ad revenue needs 1,000 subscribers plus 4,000 public watch hours in 12 months **or** 10M Shorts views in 90 days. The "expanded" lower tier (500 subscribers, 3 public uploads in 90 days, 3,000 hours or 3M Shorts views) unlocks only fan funding and Shopping - **no ad revenue**. | https://support.google.com/youtube/answer/72851?hl=en ; https://support.google.com/youtube/answer/13429240?hl=en | as of 2026-11-17 | verified_primary |
| 2 | From **1 February 2027** new applicants need 1,000 subscribers plus **8,000** watch hours in 365 days **or 20M** Shorts views in 90 days (double today's bar). Existing YPP members are not affected. Announced August 2026. | https://support.google.com/youtube/answer/72851?hl=en ; https://vidiq.com/blog/post/youtube-partner-program-changes-2027/ | announced 2026-08, effective 2027-02-01 | verified_primary |
| 3 | YouTube's "inauthentic content" policy (renamed from "repetitious content" on 15 July 2025) makes mass-produced, repetitive or template-made content ineligible for monetisation. AI use alone is not disqualifying; named violations include image slideshows / scrolling text with little narrative and AI content built on generic templates. Earnings can be withheld up to 90 days during investigation. | https://support.google.com/youtube/answer/1311392?hl=en | policy text as of 2026-11 | verified_primary |
| 4 | Enforcement is real: after the Kapwing study, YouTube terminated or wiped 16-18 of the largest AI-slop channels in late January 2026 (widely cited: 16 channels, ~35M subscribers, ~4.7B views, ~$10M estimated annual earnings; counts differ by outlet). YouTube said it "terminated several channels for violating our spam policies". | https://www.tubefilter.com/2026/01/29/youtube-ai-slop-channel-crackdown-bans/ ; https://thenextweb.com/news/youtube-ai-slop-crackdown-faceless-creators-collateral-damage | 2026-01-29 / 2026 | reported_secondary |
| 5 | The crackdown hits legitimate faceless channels too: Hollywood Reporter (13 June 2026) quotes the operator of a 1.7M-subscriber channel: "The people who do the same content as me without their face in it, most of them are getting demonetized." | https://www.hollywoodreporter.com/business/digital/faceless-creators-youtube-ai-damage-1236617586/ | 2026-06-13 | reported_secondary |
| 6 | Ukraine is on YouTube's YPP availability list and on the AdSense availability list (the YPP snapshot returned by search is old; the expanded 500-subscriber tier is reported by one third-party site as not available for Ukraine). | https://support.google.com/youtube/answer/7101720?hl=en ; https://support.google.com/adsense/answer/13402307?hl=en | snapshot age unclear | verified_primary |
| 7 | TikTok Creator Rewards Program is open only to accounts registered in 8 countries (US, UK, Germany, Japan, South Korea, France, Mexico, Brazil). **Ukraine is not eligible.** Requirements: 18+, 10,000 followers, 100,000 views in 30 days, original videos longer than 1 minute. | https://www.tiktok.com/creator-academy/en/article/creator-rewards-program ; https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en | as of 2026-11 | verified_primary |
| 8 | X retired Creator Revenue Sharing on 7 September 2026. Its replacement, Original Content Rewards, requires a **paid** Premium subscription, 500 verified followers and 500,000 verified home-timeline impressions in 90 days; copied or minimally edited content is excluded. No reliable per-impression rate found. | https://help.x.com/en/using-x/creator-revenue-sharing ; https://opentweet.io/blog/x-original-content-rewards-2026 | 2026-09 | reported_secondary |
| 9 | Facebook Content Monetization is invitation-only with no published thresholds; Ukraine is reported as eligible, and Ukrainian creators with 5,000-10,000 followers were reported receiving first payouts from January 2026. | https://dev.ua/en/news/facebook-uvimknuv-monetyzatsiiu-ukraintsiam-1770808882 ; https://contentmonetizing.com/en/how-to-get-facebook-monetization/ | 2026-02 / 2026-10 | reported_secondary |
| 10 | Revenue per 1,000 views is low: median Shorts RPM $0.07-$0.20 in most niches (274 channels; US about $0.33), median long-form RPM $2.30 (300 channels, May 2025-May 2026; $0.33 Kids to $10.22 Education & Science). Shorts were under 2% of revenue for most channels. Dataset owner is an MCN vendor. | https://air.io/en/monetization/what-rpm-can-you-expect-from-shorts-in-2026 ; https://air.io/en/air-data-findings/youtube-monetization-statistics-2026 | 2026 (data May 2025-May 2026) | reported_secondary |
| 11 | Most small channels do not reach even the subscriber threshold in a year: among 32.9M channels under 1,000 subscribers, the share reaching 1,000 within 360 days was 0.20% (no new videos), 1.86% (1-11 videos), 8.65% (12-51), 30.77% (52+). In a separate sample of 9,414 channels that did reach 1,000, the median time was ~16 months and 68% needed more than 40 videos. | https://vidiq.com/research/youtube-uploads-1000-subscribers/ ; https://vidiq.com/blog/post/youtube-subscriber-growth-statistics/ | 2026-09 / 2026 | reported_secondary |
| 12 | AI video is paid-only at API level: Veo 3.1 $0.40/s (720p/1080p), $0.60/s (4K); Veo 3.1 Fast $0.10/s (720p), $0.12/s (1080p); Veo 3.1 Lite $0.05/s (720p). No free API tier for Veo or for the Nano Banana image models (about $0.034-$0.134 per 1K image). | https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing ; https://ai.google.dev/gemini-api/docs/pricing | as of 2026-11 | verified_primary |
| 13 | OpenAI Sora is gone: consumer app ended 26 April 2026, API discontinued 24 September 2026, no replacement listed. Any pipeline design that assumes Sora is obsolete. | https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation | 2026-09-24 | verified_primary |
| 14 | Other video APIs (secondary, conflicting): Kling 3.0 $0.084-$0.168/s (720p-1080p, without/with audio), Runway Gen-4.5 about $0.12/s, Seedance 2.0 about $0.15/s at 720p. ElevenLabs Free (10,000 credits/month) has **no commercial licence**; Starter is $6/month for 30,000 credits. | https://apiframe.ai/blog/ai-video-api-pricing-2026 ; https://www.cartesia.ai/learn/elevenlabs-pricing | 2026 | reported_secondary |
| 15 | Own calculation: a channel that only just clears the 8,000-hour bar (about 120,000-240,000 long-form views a year) earns roughly $280-$550 a year at the median $2.30 RPM; a 45-second fully generated Short costs $2.25-$18 and needs about 22,000-180,000 monetised views to pay back at $0.10 RPM. Median outcome for a new automated channel in 12 months is $0 platform revenue. | derived from claims 2, 10, 11, 12 | 2026-11-17 | inference |

## Detailed findings

### 1. YouTube Partner Program: thresholds, Ukraine, policy, enforcement, disclosure

**Takeaway.** YouTube monetisation is available in Ukraine, but the entry bar doubles on 1 February 2027, the lower tier pays no ad revenue, and the policy text names exactly the cheap automated formats (slideshows, templated AI narration) as non-monetisable. Enforcement in 2026 has been visible and has produced collateral damage among legitimate faceless channels.

**Cited findings**

Thresholds
- Full YPP (ads and Premium revenue share): 1,000 subscribers plus either 4,000 qualified public watch hours in the last 12 months or 10 million qualified public Shorts views in the last 90 days. - [YouTube Help 72851](https://support.google.com/youtube/answer/72851?hl=en) (official page via search)
- Expanded YPP: 500 subscribers, 3 valid public uploads in the last 90 days, and 3,000 watch hours in 12 months or 3 million Shorts views in 90 days. It gives fan funding and Shopping features only; ad and Premium revenue sharing still requires the 1,000-subscriber tier. - [YouTube Help 13429240](https://support.google.com/youtube/answer/13429240?hl=en)
- Watch hours from Shorts, private/unlisted/deleted videos and ad campaigns do not count towards the watch-hour threshold. The two routes (hours or Shorts views) do not combine. - [YouTube Help 72851](https://support.google.com/youtube/answer/72851?hl=en)
- Meeting the numbers only allows an application; the channel then goes through a review against policies. - [YouTube Help 72851](https://support.google.com/youtube/answer/72851?hl=en)
- **Change effective 1 February 2027:** entry thresholds for new creators become 8,000 qualified watch hours in the last 365 days or 20M qualified Shorts views in the last 90 days, still with 1,000 subscribers. Current members are not affected ("If you are already in YPP, your status is not impacted by this update"). - [YouTube Help 72851](https://support.google.com/youtube/answer/72851?hl=en); [vidIQ](https://vidiq.com/blog/post/youtube-partner-program-changes-2027/); [Tubefilter, 10 Aug 2026](https://www.tubefilter.com/2026/08/10/youtube-partner-program-ad-eligibility-requirements-shorts/amp/); [ppc.land](https://ppc.land/new-youtube-creators-face-8-000-hour-bar-for-ad-revenue-from-february-2027/)
- The 500-subscriber tier is reported as unchanged by the 2027 update, but sources are not unanimous. - [outlierkit](https://outlierkit.com/resources/youtube-partner-program-changes-2027/)

Ukraine
- Ukraine appears in the official YPP availability list and in the AdSense availability list (EMEA). The YPP snapshot the search returned is several years old. - [YouTube Help 7101720](https://support.google.com/youtube/answer/7101720?hl=en); [AdSense Help 13402307](https://support.google.com/adsense/answer/13402307?hl=en)
- One third-party guide says the 500-subscriber expanded tier is not listed for Ukraine; third-party country counts range from 138 (standard) and 99 (expanded tier) to "195". Not confirmed against Google. - [contentmonetizing.com](https://contentmonetizing.com/en/youtube-monetization-countries/); [air.io](https://air.io/en/monetization/youtube-partner-program-requirements-2026-the-complete-guide)
- Non-US creators face US withholding on earnings from US viewers only: without a tax form the default is reported as 24% of all earnings (some guides say 30% of US-sourced earnings); with a W-8BEN and a treaty the rate on royalties is 0-15% depending on the country. The Ukraine-specific treaty rate was not confirmed in this session. - [vidIQ](https://vidiq.com/blog/post/non-u-s-creators-24-percent-tax-youtube-revenue/); [fluxnote](https://fluxnote.io/guides/youtube-tax-withholding-w8ben-2026)

Inauthentic / mass-produced content policy
- On 15 July 2025 YouTube renamed the "repetitious content" policy to "inauthentic content" and clarified that it covers repetitive or mass-produced content; YouTube states this content "has always been ineligible for monetisation". - [YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en)
- Definition: content that appears template-made or that viewers may find repetitive after watching several videos in a row from one channel. - [YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en)
- Named violations: image slideshows, templated storylines or scrolling text with little narrative or commentary; characters placed in the same situation with the same outcome; AI-generated content built on generic templates that looks mass-produced and lacks the creator's own insight. - [YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en)
- Allowed: shared intro/outro with differing main content; a series with recurring characters or a review channel where each video has a distinct storyline or focus; use of automated tools or AI, provided the final video shows creative vision and provides value. - [YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en)
- The separate Spam policy gives as an example of automated mass production a channel that uses the same background music and repetitive AI imagery across many videos, each reading out an AI-generated script; "a few variations" are acceptable, flooding the platform is not. - [YouTube Help 2801973](https://support.google.com/youtube/answer/2801973?hl=en)
- Consequence: earnings may be withheld or adjusted while YouTube investigates, delaying payment by up to 90 days. - [YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en)
- YouTube's creator liaison Rene Ritchie called the July 2025 change "a minor update" and said mass-produced content had been ineligible "for years"; AI itself is not banned. - [Medium post citing Ritchie](https://mateostarcevicfilipovic.medium.com/youtube-quietly-demonetizes-faceless-ai-channels-since-july-2025-30b3d2daaf2e) (secondary)

Documented enforcement, 2025-2026 (chronology)
- Late 2025: Kapwing reviewed about 15,000 trending channels (top 100 per country) and found 278 producing only AI slop, with more than 63B views, 221M subscribers and an estimated ~$117M a year *if monetised* (an estimate of potential revenue, not confirmed earnings). 21% of the first 500 Shorts shown to a brand-new account were AI slop. - [Kapwing](https://www.kapwing.com/blog/ai-slop-report-the-global-rise-of-low-quality-ai-videos/); [Search Engine Journal](https://www.searchenginejournal.com/youtubes-ai-slop-problem-and-how-marketers-can-compete/567297/)
- 29 December 2025: the Guardian reported that more than 20% of videos shown to new users are AI slop and that nearly 10% of the fastest-growing channels were AI slop. - [Kapwing](https://www.kapwing.com/blog/ai-slop-report-the-global-rise-of-low-quality-ai-videos/); [ukranews summary](https://ukranews.com/en/news/1125233-algorithms-promote-ai-garbage-low-quality-content-flooded-youtube-and-brings-in-hundreds-of-millions)
- 21 January 2026: CEO Neal Mohan's annual letter named "managing AI slop" a 2026 priority and said YouTube is extending its spam and clickbait systems to reduce low-quality repetitive content. - [CNBC](https://www.cnbc.com/2026/01/21/youtube-chief-says-managing-ai-slop-is-a-priority-for-2026-.html)
- Late January 2026: top AI-slop channels from the Kapwing list disappeared. Counts differ: "at least 18" (Tubefilter), "16 of the top 100" taken down or wiped (Gizchina), "11 terminated and 6 wiped" (Dexerto via others). The commonly repeated aggregate is 16 channels, ~35M subscribers, ~4.7B lifetime views, ~$10M estimated annual earnings. Removed channels included CuentosFacianantes and Imperio de Jesus (5.8M subscribers). YouTube: "We terminated several channels for violating our spam policies." Not every channel named in the study was penalised. - [Tubefilter, 29 Jan 2026](https://www.tubefilter.com/2026/01/29/youtube-ai-slop-channel-crackdown-bans/); [Gizchina](https://www.gizchina.com/youtube/youtube-removes-major-ai-slop-channels-after-study-reveals-billions-of-views); [The Next Web](https://thenextweb.com/news/youtube-ai-slop-crackdown-faceless-creators-collateral-damage); [Digital Camera World](https://www.digitalcameraworld.com/tech/artificial-intelligence/youtube-gets-tough-on-ai-slop-ruining-the-party-for-million-dollar-brain-rot-video-channels)
- 17 March 2026: YouTube began showing viewers a prompt asking whether a video "feels like AI slop" (scale from "not at all" to "extremely"). - [dig.watch](https://dig.watch/updates/youtube-enlists-users-to-rate-videos-as-ai-slop-in-content-quality-push); [Daily Dot](https://dailydot.com/youtube-prompt-asking-does-this-feel-like-ai-slop)
- 1 April 2026: about 200 organisations signed an open letter (Fairplay) demanding action on AI slop on YouTube Kids. - [Fortune](https://fortune.com/2026/04/01/ai-slop-200-organizations-letter-youtube-google/)
- 13 June 2026: Hollywood Reporter, "Faceless Creators Take a Hit As YouTube Cracks Down on AI Slop" - Craig Billings (Doctor NOS, ~1.7M subscribers): "most of them are getting demonetized". Related coverage says recommendations now favour videos with a real human on camera and some creators hire on-camera hosts. - [Hollywood Reporter](https://www.hollywoodreporter.com/business/digital/faceless-creators-youtube-ai-damage-1236617586/)
- Collateral damage: legitimate educational channels (exam-prep) and a 588,000-subscriber Bible-story channel were reported demonetised for "inauthentic and mass-produced content". - [The Next Web](https://thenextweb.com/news/youtube-ai-slop-crackdown-faceless-creators-collateral-damage); [TechTimes, 15 Jul 2026](https://www.techtimes.com/articles/320629/20260715/youtube-wiped-35m-subscribers-over-ai-slop-now-its-judging-your-taste.htm)
- YouTube is reported to evaluate whole channels rather than single videos. - [TubeBuddy](https://www.tubebuddy.com/blog/youtube-ai-demonetization-how-to-spot-risk/) (vendor blog)

Synthetic-content disclosure
- Creators must disclose realistic altered or synthetic content (a real person appearing to say or do something they did not, altered footage of a real event or place, a realistic scene that did not occur). Not required for clearly unrealistic or animated content, minor edits, or productivity uses such as scripts, ideas and captions. - [YouTube Help 14328491](https://support.google.com/youtube/answer/14328491?hl=en); [YouTube Blog](https://blog.youtube/news-and-events/disclosing-ai-generated-content/)
- YouTube may apply labels itself (its own GenAI tools, C2PA metadata, internal detection); some labels are permanent. Creators who consistently fail to disclose may face content removal or suspension from YPP. Labels alone do not affect recommendations or monetisation eligibility. More prominent label placement was slated to begin in May 2026. - [YouTube Help 15447836](https://support.google.com/youtube/answer/15447836?hl=en); [YouTube Blog](https://blog.youtube/news-and-events/improving-ai-labels-viewers-creators/)

Automation plumbing
- Google's YouTube Data API revision history reportedly states (2 November 2026) that videos uploaded through `videos.insert` from unverified API projects are no longer restricted to private mode, reversing the 28 July 2020 rule. Other Google pages still describe the old restriction; the search extract was internally confusing, so this needs a direct check before the pipeline relies on it. - [YouTube Data API revision history](https://developers.google.com/youtube/v3/revision_history?hl=en)

**Inferences**
- A channel started today has 76 days before the bar doubles. Given a ~16-month median to 1,000 subscribers among channels that *succeed*, a new FactoryOS channel should be planned against the 8,000-hour / 20M-Shorts bar, not the current one.
- 8,000 hours is 480,000 minutes: about 120,000 views at a 4-minute average view duration, 240,000 at 2 minutes. The required pace is **about 22 public watch hours every day for a year**. The Shorts route needs about 222,000 views a day for 90 days.
- The cheapest fully automatable formats (stock or AI stills + TTS + templated script, published at volume) are the formats the policy names. "Autonomous" and "monetisable" pull in opposite directions on YouTube.
- Scale raises risk rather than diluting it: the January 2026 terminations targeted the *largest* AI channels, and review is at channel level.

**Gaps**
- Official ad revenue share (55% long-form, 45% of the Shorts creator pool) - prior knowledge, not re-verified in this session.
- AdSense payment threshold ($100) and Ukraine payout methods - prior knowledge, unverified.
- Whether an application submitted before 1 February 2027 is judged on the old thresholds if reviewed later - not found.
- US-Ukraine treaty withholding rate on royalties (I believe 10%) - unverified.
- Current YouTube Data API quota and the per-upload cost - not confirmed.
- No official count of channels demonetised under the inauthentic-content policy in 2026; one claim of "18,000 channels in January 2026" comes from a weak source and conflicts with all others.
- Nothing found for a specific enforcement wave in October-November 2026.

### 2. Revenue reality: RPM, time to monetisation, share that gets there, case studies

**Takeaway.** Ad income per view is small and heavily skewed by format, niche and viewer country; the typical new channel does not qualify within a year; the well-known AI-channel successes are outliers, several of which were later terminated.

**Cited findings**
- Shorts: median RPM $0.07-$0.20 per 1,000 views in most niches, $0.97-$1.48 for Music (274 channels). By niche the range is $0.02-$1.48; Shorts earn about 3-14% of long-form RPM, so 11,000-34,000 Shorts views equal the revenue of 1,000 long-form views. For most channels Shorts were under 2% of total revenue. - [AIR Media-Tech](https://air.io/en/monetization/what-rpm-can-you-expect-from-shorts-in-2026); [AIR](https://air.io/en/youtube-hacks/should-you-chase-shorts-views-or-double-down-on-long-form-for-channel-growth); [AIR](https://air.io/en/trending/youtube-updates-its-monetization-rules-what-creators-need-to-know)
- Shorts RPM by viewer country (AIR partner data): US ~$0.328, Switzerland $0.205, Australia $0.193, South Korea $0.185, UK $0.166, Canada $0.165, Germany $0.163. Other trackers: US/UK $0.18-$0.30, India/Pakistan/Bangladesh $0.02-$0.05; "most creators" $0.01-$0.07. - [AIR](https://air.io/en/monetization/comparing-shorts-monetization-to-tiktok-creator-rewards); [fluxnote](https://fluxnote.io/guides/youtube-shorts-rpm-by-country); [miraflow](https://miraflow.ai/blog/youtube-shorts-rpm-2026-real-ranges-by-niche)
- Long-form: median RPM about $2.30 across 300 channels (May 2025-May 2026; 3,595 channel-months via the YouTube Analytics API). By niche: Education & Science $10.22, Transport $5.69, Health & Sport $1.23, Kids & Teens $0.33. - [AIR](https://air.io/en/air-data-findings/youtube-monetization-statistics-2026); [AIR](https://air.io/en/air-data-findings/which-youtube-niche-makes-the-most-money-in-2026-ranked-by-real-rpm-and-cpm)
- Geography (CPM, not RPM; AIR table from June 2025, 3,000+ channels): United States $14.67 versus India $0.74. - [mubert summary of AIR data](https://mubert.com/blog/youtube-rpm-by-niche-and-country)
- YouTube publishes no official RPM benchmarks by niche or country; all tables are third-party datasets. - [overseeros](https://www.overseeros.com/blog/youtube-rpm-by-niche)
- Reaching 1,000 subscribers (vidIQ, 32.9M channels that started under 1,000, compared 360 days apart, September 2026): 0.20% with no net new videos (56,008 of 27,360,211), 1.86% with 1-11, 8.65% with 12-51, 30.77% with 52 or more. vidIQ stresses association, not causation. - [vidIQ research](https://vidiq.com/research/youtube-uploads-1000-subscribers/)
- Among 9,414 channels created after 2023 that recently crossed 1,000 subscribers, the median time was about 16 months and 68% needed more than 40 videos. (Survivors only.) - [vidIQ](https://vidiq.com/blog/post/youtube-subscriber-growth-statistics/)
- Stock of channels (vidIQ, July 2026, 61M channels with at least one public subscriber): 40.6% have 1,000+ subscribers, 7.9% 10,000+, 1.3% 100,000+, 0.13% 1M+. Against all ~113M channels the commonly cited share above 1,000 is ~8.9%. Neither figure equals "monetised" (watch hours and policy review also apply). - [vidIQ research](https://vidiq.com/research/youtube-subscriber-benchmarks-2026/); [teleprompter.com](https://www.teleprompter.com/blog/vlogging-statistics)
- Case studies (all secondary; treat as anecdote): Adavia Davis, 22, reported at ~$700,000 a year from a faceless network (flagship "Boring History"), said to have been checked by Fortune against AdSense records - I could only find this via a Medium post. Bandar Apna Dost (India): estimated $4.25M a year from 2.4B views in the Kapwing study - an estimate. A self-reported small case: $895 total from 12 videos over two years. Guides say most channels earn nothing for 6-12 months. A modelled (not observed) ten-channel portfolio with suppressed reach loses about $260 a month. - [Medium](https://mateostarcevicfilipovic.medium.com/youtube-quietly-demonetizes-faceless-ai-channels-since-july-2025-30b3d2daaf2e); [Medium, "Most Lose Money"](https://medium.com/@automation.labs/faceless-ai-youtube-pays-50k-a-month-most-lose-money-9120e2906541); [Kapwing](https://www.kapwing.com/blog/ai-slop-report-the-global-rise-of-low-quality-ai-videos/)

**Inferences**
- Revenue at the threshold: 8,000 hours a year at a 4-minute average view duration is ~120,000 views, i.e. ~$276 a year at $2.30 RPM; at a 2-minute duration ~240,000 views, ~$552 a year. A channel that barely qualifies earns tens of dollars a month.
- $1,000 a month of ad revenue needs roughly 435,000 long-form views a month at the median RPM, or 5-14 million Shorts views a month at $0.07-$0.20.
- A Ukrainian- or Russian-language audience would earn well below these tier-1 medians (CPM gap of an order of magnitude between the US and low-income markets); a Ukraine-based founder therefore has to produce for an English-speaking audience, where competition and saturation are highest.
- Probability that a new automated channel reaches *full* YPP in 12 months: my estimate is 5-15%. Upper bound is the 30.8% of weekly-or-better uploaders that reach 1,000 subscribers; the 8,000-hour requirement and the policy review cut that further.

**Gaps**
- No independent, auditable income statement of an AI/faceless channel was retrievable (Fortune and Hollywood Reporter pages could not be opened).
- No data on RPM for Ukrainian-audience traffic.
- No official figure for the share of channels in YPP.

### 3. Other platforms: TikTok, Facebook / Instagram, X, Telegram

**Takeaway.** For a Ukraine-based account most "pay per view" programmes are closed (TikTok), invitation-only (Facebook), paid-subscription-gated (X) or small and crypto-denominated (Telegram). None is a realistic primary income line.

**Cited findings**
- TikTok Creator Rewards: open to creators in the United States, United Kingdom, Germany, Japan, South Korea, France, Mexico and Brazil; the account must be registered there. Requirements: 10,000 authentic followers, 100,000 authentic views in the previous 30 days, adult (19 in South Korea), personal account in good standing, original videos of at least one minute; Duet, Stitch, Photo Mode and paid promotions are excluded; Business Accounts do not qualify. - [TikTok Creator Academy](https://www.tiktok.com/creator-academy/en/article/creator-rewards-program); [TikTok US terms](https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en)
- Only views from the eligible countries count as qualified views (as reported from TikTok's terms). - [monetizednow.com](https://monetizednow.com/creator-rewards-countries)
- Ukraine: Creator Rewards is not available; LIVE gifts and brand deals are the practical options for Ukrainian creators; TikTok has published no expansion schedule. - [Komersant Ukrainian](https://komersant.ua/en/yak-zaroblyati-v-tiktok-v-ukraini-perevireni-sposobi-monetizaczii/); [Spilno Agency](https://spilnoagency.com.ua/en/instructions-us/monetization-on-tiktok-how-it-works)
- Facebook Content Monetization: invitation-only (interest form, not an application); Meta states only an "established presence" of 30+ days and residency in an available country, with no public follower/view thresholds; around 70 countries; Ukraine reported as officially eligible (one page says the opposite - likely an error). Ukrainian creators with 5,000-10,000 followers reportedly began receiving first payments in January 2026. Reels must be at least 10 seconds and in listed languages/countries. - [dev.ua](https://dev.ua/en/news/facebook-uvimknuv-monetyzatsiiu-ukraintsiam-1770808882); [hi-tech.ua](https://hi-tech.ua/en/ukrainian-users-will-be-able-to-monetize-pages-with-5000-followers-on-facebook/); [contentmonetizing.com](https://contentmonetizing.com/en/how-to-get-facebook-monetization/); [insighthive](https://insighthive.app/resources/facebook-content-monetization-eligible-countries)
- X: Creator Revenue Sharing was sunset on 7 September 2026 (new enrolments stopped 7 August 2026). Replacement "Original Content Rewards": Premium / Premium+ / Premium Business subscription, 500 verified followers, 500,000 verified home-timeline impressions in 90 days (replies excluded; a 3M figure is reported but unconfirmed), 18+, supported country (116-120 reported), original content; copied or minimally edited content excluded; payout every two weeks, $30 minimum; non-US creators paid via Stripe. - [X Help](https://help.x.com/en/using-x/creator-revenue-sharing); [opentweet.io](https://opentweet.io/blog/x-original-content-rewards-2026); [climbx.so](https://climbx.so/blog/x-original-content-rewards-3m-impressions)
- X earnings: no reliable rate. Third-party estimates conflict: $100-$800 a month at 5-25M monthly impressions versus $20-$120 at 50M. - [xpert.so](https://xpert.so/blog/how-much-does-x-actually-pay-creators-in-2026-34363); [nlosmm](https://nlosmm.com/blog/how-much-can-you-earn-from-x-twitter-2026)
- Telegram: owners of public channels with at least 1,000 subscribers receive 50% of revenue from Telegram's own ads shown in the channel, paid in Toncoin (withdrawable via Fragment or reusable for ads). Launch coverage (2024) said "nearly one hundred countries"; no current official country list was found. - [TechCrunch, 28 Feb 2024](https://techcrunch.com/2024/02/28/telegram-is-launching-ad-revenue-sharing-next-month-using-toncoin); [tguard.pro](https://tguard.pro/en/blog/telegram-channel-monetization-eligibility/)

**Inferences**
- TikTok has zero direct revenue value for a Ukrainian account; it is distribution only.
- X now requires a paid subscription before any payout, which collides with the zero-additional-spend rule, and Stripe payouts are a further obstacle to check for a Ukrainian resident (Stripe's Ukraine availability not verified here).
- Facebook is the only programme with reported small-account payouts in Ukraine, but entry is at Meta's discretion and unforecastable.

**Gaps**
- Instagram monetisation status for Ukraine in 2026 - search budget ran out; not verified.
- TikTok's rules on AI-generated content within Creator Rewards - not verified.
- Telegram ad-share earnings per 1,000 views and whether Telegram ads serve to Ukrainian audiences - not found.
- Whether Ukraine is among X's supported countries - not verified.

### 4. Affiliate and lead-generation revenue through content

**Takeaway.** Affiliate income needs no platform threshold, so it is the fastest *theoretical* first dollar, but it only works on purchase-intent content with real traffic. The available benchmarks are vendor data and Amazon cut rates in 2026.

**Cited findings**
- YouTube description-link click-through: 0.5-3% of views (guides); median 1.2% for pinned description links and 0.4% for deep links (TrackRev). - [wecantrack](https://wecantrack.com/insights/youtube-affiliate-marketing-statistics/); [TrackRev](https://www.trackrev.io/blog/link-tracking-benchmarks-2026)
- Click-to-sale conversion: about 3.2% average, 4.1% for review videos (vendor statistics page); other guides give 2-8%. - [zebracat](https://www.zebracat.ai/post/youtube-affiliate-marketing-statistics); [influencerfee](https://influencerfee.com/blog/youtube-influencer-affiliate-rates/)
- Revenue per click: median $1.05, top quartile $2.60 for YouTube description links (TrackRev). - [TrackRev](https://www.trackrev.io/blog/link-tracking-benchmarks-2026)
- Amazon Associates: rates fell in 18 of 27 categories between April 2020 and January 2026; trade coverage reports further cuts of up to 50% between March and May 2026 and an Operating Agreement update on 14 April 2026. An unofficial table lists Amazon Games 20%, Luxury Beauty 10%, Amazon Haul 7%, music/handmade/digital video 5%, devices/fashion/jewellery 4%. - [getlasso](https://getlasso.co/amazon-affiliate-commission-rate/); [shopifreaks](https://www.shopifreaks.com/amazon-quietly-slashed-associates-affiliate-commission-rates-by-up-to-50-across-publisher-ecosystem-and-gutted-reporting-tools/); [karooya](https://www.karooya.com/blog/amazon-affiliate-commission-cuts-2026-what-changed-and-what-it-means-for-advertisers/)

**Inferences (own arithmetic, stated assumptions)**
- Benchmark route: 1,000 views x 1.2% click-through = 12 clicks x $1.05 = about $12.60 per 1,000 views; the 0.5-3% band gives $5-$32. These figures come from creators who already run purchase-intent content and track links, so they are an upper band, not an expectation for generic AI content.
- Bottom-up route, physical goods: 1,000 views x 1% x 3.2% = 0.32 orders x $50 basket x 4% = about $0.64 per 1,000 views. Software with a $30 commission: 0.32 x $30 = about $9.60 per 1,000 views.
- Realistic planning range: $0.5-$15 per 1,000 *purchase-intent long-form* views; close to $0 for entertainment Shorts.
- At a new channel's traffic (hundreds to a few thousand views a month) this is $0-$25 a month. Affiliate is faster to a first dollar than ads but does not change the order of magnitude.
- Lead generation for the founder's *own* paid offer is the only variant where a small audience can matter: one closed B2B client is worth more than a year of ad revenue from a barely-monetised channel. I found no sourced cost-per-lead benchmarks in this session; this is reasoning, not data.

**Gaps**
- FTC Endorsement Guides (clear and conspicuous disclosure of material connections) and YouTube's paid-promotion checkbox - prior knowledge, not re-verified this session; the report should cite ftc.gov directly.
- Whether Shorts links are clickable (I believe description and comment links on Shorts are not) - unverified.
- Lead-generation benchmarks (cost per lead, lead-to-customer rates) - none collected.
- Affiliate programme rules on AI-generated promotional content - not checked.

### 5. Production costs as of November 2026 and what free tiers allow

**Takeaway.** Generated video is cheap per second but not free, and a year of pre-monetisation output at paid rates is a four-figure sunk cost. Under "zero additional spend" only stock/diagram footage, open-source voice and existing chat subscriptions are available - the format most exposed to the inauthentic-content policy.

**Cited findings**
- Google Veo (Google Cloud pricing table): Veo 3.1 $0.40/s at 720p/1080p, $0.60/s at 4K; Veo 3.1 Fast $0.10/s (720p), $0.12/s (1080p); Veo 3.1 Lite $0.05/s (720p). Gemini Omni Flash video output $0.10/s. Some aggregators list $0.20/s without audio. - [Google Cloud pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing); [Google blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-omni-flash-nano-banana-2-lite/); [invideo, Aug 2026](https://invideo.io/blog/ai-video-model-pricing/)
- No free API tier found for Veo; free "Fast" generations mentioned in the forum apply to AI Ultra subscribers in Flow. - [Google AI forum](https://discuss.ai.google.dev/t/veo-3-video-model-api-pricing/106415)
- OpenAI Sora: app ended 26 April 2026; API discontinued 24 September 2026 (announced 24 March 2026); no replacement. - [OpenAI Help](https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation)
- Kling 3.0 (official API as reported): $0.084/s at 720p without audio, $0.126 with audio; $0.112 / $0.168 at 1080p; $0.42 at 4K; sold as prepaid packages. Other sources give $0.029-$0.11/s depending on reseller and variant. - [apiframe](https://apiframe.ai/blog/ai-video-api-pricing-2026); [cloudzero](https://www.cloudzero.com/blog/kling-ai-pricing/); [invideo](https://invideo.io/blog/ai-video-model-pricing/)
- Runway Gen-4.5: 12 credits per second at $0.01 per credit = $0.12/s (2-10 s clips, 720p); Runway's docs reportedly also show 25 credits/s; marketplaces ~$0.17/s. - [apiframe Runway guide](https://apiframe.ai/guides/runway-api-guide)
- Seedance 2.0: about $0.15/s at 720p ($0.07 at 480p, $0.37 at 1080p); resellers $0.045-$0.05/s. Hailuo 2.3: flat per clip "from $0.41" (single source). - [teamday.ai](https://www.teamday.ai/blog/best-ai-video-models-2026); [apiframe](https://apiframe.ai/blog/ai-video-api-pricing-2026)
- Images (Gemini API): Nano Banana 2 about $0.067 per 1K image; Nano Banana 2 Lite about $0.034 (1K only); Nano Banana Pro about $0.134 (1K/2K) and $0.24 (4K). No free API tier for the image models. Imagen is no longer offered through the Gemini API. - [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing); [Gemini API image docs](https://ai.google.dev/gemini-api/docs/image-generation)
- Gemini API free tier: text models only with tight limits (one October 2026 reading: 5 requests/minute and 20 requests/day on a Flash model); image, video and music need a paid project; sources conflict on whether TTS models have a free tier. Limits are per project and shown in AI Studio. - [dev.to](https://dev.to/hassann/gemini-api-free-tier-in-2026-limits-models-and-when-you-get-billed-4081); [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- Voice: ElevenLabs Free - 10,000 credits a month, no commercial licence, attribution required. Starter $6/month - 30,000 credits, commercial rights. Creator $22/month - 121,000 credits. Annual billing about 17% cheaper. - [cartesia summary](https://www.cartesia.ai/learn/elevenlabs-pricing); [cloudzero](https://www.cloudzero.com/blog/elevenlabs-pricing/)
- Consumer free routes (weak sources): Google Flow about 50 free credits a day (roughly four 8-second 720p clips), watermark, limited commercial terms; YouTube's built-in Shorts AI tools (Veo 3 Fast / Dream Screen) are reported free at 480p inside the app. Neither is an API. - [thehype.news](https://thehype.news/best-free-ai-video-generator/); [revid.ai](https://www.revid.ai/blog/ai-youtube-shorts)

**Inferences - per-video cost (assumptions: 1 credit per character for TTS; no retakes unless stated)**

| Format | Inputs | Cash cost per video |
|---|---|---|
| 45 s Short, fully generated video, Veo 3.1 Lite | 45 s x $0.05 | $2.25 (about $4.50 with one retake per shot) |
| 45 s Short, Veo 3.1 Fast or Omni Flash | 45 s x $0.10 | $4.50 (about $9 with retakes) |
| 45 s Short, Kling 3.0 720p with audio | 45 s x $0.126 | $5.67 |
| 45 s Short, Veo 3.1 | 45 s x $0.40 | $18.00 |
| 45 s Short, 8 AI stills + TTS | 8 x $0.034-$0.067 + ~700 characters x $0.0002 | $0.41-$0.68 |
| 8 min long-form, 40 AI stills + TTS | 40 x $0.034-$0.067 + ~7,200 characters | $2.70-$4.10 |
| 8 min long-form, fully generated video | 480 s x $0.05-$0.40 | $24-$192 |
| 8 min long-form, stock footage + open-source voice + ffmpeg on the existing server | - | about $0 cash (compute and founder time only) |

- Break-even views on generation cost alone: a $4.50 Short needs 45,000 monetised views at $0.10 RPM; an $18 Short needs 180,000; a $3.40 stills-based long-form video needs about 1,500 views at $2.30 RPM; a $48 generated long-form video needs about 21,000.
- A daily generated Short costs about $135-$270 a month (Lite or Fast, with retakes). Twelve pre-monetisation months means $1,600-$3,200 spent before the first ad dollar - not compatible with the owner's policy.
- The stills + TTS format is the only paid format with trivial unit cost, and it is the one the policy describes as "image slideshows ... with little narrative".
- ElevenLabs Free cannot be used for monetised output (no commercial licence); 10,000 credits is also only about one 8-minute script.

**Gaps**
- Open-source voice (Kokoro, Piper) licences and stock-footage licences (Pexels and similar) - not verified in this session; from prior knowledge they permit commercial use, but that must be checked.
- Whether automated use of consumer chat subscriptions (Claude Pro, ChatGPT) for a publishing pipeline is permitted by their terms - out of scope here, but it decides whether the "free" script step is really free.
- Kling, Runway, Hailuo and Seedance prices were not confirmed on the vendors' own pages.

### 6. Unit economics and scenarios (all inference; assumptions explicit)

Assumptions: English-language channel aimed at tier-1 viewers; application under the post-February-2027 thresholds; long-form RPM $1.5-$4 (median $2.30); Shorts RPM $0.03-$0.20; cash cost $0-$50 a month (zero-spend to minimal voice/image budget); founder approves every upload. Taxes and US withholding not deducted.

**One channel, first 12 months**

| | Pessimistic | Base | Optimistic |
|---|---|---|---|
| My probability estimate | 70-85% | 10-25% | under 5% |
| Outcome | Never reaches 1,000 subscribers + 8,000 hours, or is refused in review as inauthentic | Qualifies in month 9-14 on long-form and passes review | Breakout by month 6-9 |
| Views (12 months) | 5,000-100,000 | 150,000-600,000 long-form | 5M+ long-form or 100M+ Shorts |
| Subscribers | 50-600 | 1,000-5,000 | 50,000+ |
| Leads / affiliate sales | 0-few | tens of clicks a month | meaningful |
| Platform revenue in 12 months | $0 | $0-$600 (0-3 monetised months) | $10,000-$40,000 |
| Affiliate revenue in 12 months | $0-$50 | $50-$500 | $1,000+ |
| Cash cost in 12 months | $0-$400 | $0-$600 | $600-$3,000 |
| Net profit in 12 months | -$400 to +$50 | -$400 to +$500 | $8,000-$35,000 |
| Steady-state after month 12 | n/a | $30-$500 net a month | $3,000-$6,000 a month while it lasts |
| Main way it ends | abandonment | demonetisation for inauthentic content; RPM drift | termination (largest AI channels were the January 2026 targets) |

- Time to first dollar from platform ads: earliest realistic 6-9 months, typical 12-18 months, most channels never. Add the payment threshold and a month of payment lag.
- Time to first dollar from affiliate links: 1-3 months *if* content is purchase-intent and gets a few thousand views; amounts are single or double digits.
- Break-even on cash is trivial at zero spend and meaningless: the real cost is founder hours (approval of every video, niche research, fixing the pipeline) and the opportunity cost of not selling something.

**Portfolio of 10 channels**
- If outcomes were independent at 10-20% each, 1-2 channels would qualify in a year; expected platform revenue stays in the low hundreds of dollars a month.
- They are not independent: shared templates, voice and pipeline are the "mass-produced" signature, review is at channel level, and a policy action on one channel can extend to associated channels (prior knowledge of YouTube's circumvention rules; not re-verified here).
- The human approval gate scales linearly: 10 channels publishing daily means ~300 approvals a month - the founder becomes a full-time content moderator, which defeats the "autonomous" premise.
- Cost and API-quota load also scale linearly while revenue per channel does not improve.

**Key risks:** policy change (thresholds doubled once already, August 2026); inauthentic-content demonetisation and payment holds of up to 90 days; termination; saturation (a fifth to a third of the Shorts feed is already AI-made per Kapwing); viewer-feedback signals against AI slop (March 2026 prompt); copyright and likeness claims on generated or stock material; brand-safety exclusion; vendor churn (Sora discontinued; Imagen removed from the Gemini API; Amazon commission cuts; X programme replaced) - four programme or vendor discontinuations in one year among the inputs to this model.

### 7. What can be automated, what needs human judgment, and a 30-60 day test

**Automatable without breaching rules (inference):** topic and keyword research, outline drafts, script drafts, voice synthesis, captioning, clipping and reformatting, thumbnail variants, scheduling, metadata, analytics collection, weekly performance reports, affiliate-link hygiene.

**Needs a human to stay inside the rules (inference tied to the policy text in section 1):**
- An original angle, commentary or first-hand experience in each video - the policy's test is "creative vision" and the creator's "own insight".
- Fact checking and the realistic-synthetic-content disclosure decision per upload.
- Rights clearance for footage, music, voices and likenesses.
- Affiliate / sponsorship disclosure and the truthfulness of product claims.
- The final publish decision (already an owner invariant).
- Reading the channel "in a row" as a reviewer would: do ten consecutive videos look templated?

**Data that confirms or refutes the hypothesis in 30-60 days (thresholds are my heuristics, except the first, which is arithmetic):**
1. Public watch hours per day. The 8,000-hour bar equals ~22 hours a day. If, after 20-30 long-form uploads, the trailing-14-day average is below ~3 hours a day and not growing week on week, the ad route is refuted for that channel.
2. Shorts route: trailing-7-day views against the required ~222,000 a day. Below ~5,000 a day after 45 Shorts means the Shorts route is refuted.
3. Subscribers gained per 1,000 views (below ~2 means no audience is forming) and average percentage viewed (below ~30% on long-form suggests content viewers treat as filler).
4. Any "limited" or "reused/inauthentic" signals in YouTube Studio, or reach collapsing after a batch of similar uploads.
5. Affiliate: clicks per 1,000 views and at least one tracked conversion; zero conversions after 5,000 purchase-intent views refutes that line for the niche.
6. Lead generation for the founder's own offer: number of qualified enquiries (replies, booked calls, sign-ups to MyCast/MyBrief) attributable to content. Even 2-3 real conversations in 60 days is a stronger commercial signal than any view count.
7. Founder hours per published video. If approval and fixes take more than ~15 minutes per video, the "autonomous" claim fails on labour, not on technology.

## Counter-evidence and caveats

- **AI channels do make money - some of them a lot.** Kapwing's 278 channels had 63B views and an estimated $117M a year; individual operators are reported at $700K a year. The model is not impossible; it is a hit-driven lottery whose winners became the January 2026 enforcement targets. Not every channel named in the study was penalised. ([Kapwing](https://www.kapwing.com/blog/ai-slop-report-the-global-rise-of-low-quality-ai-videos/); [Tubefilter](https://www.tubefilter.com/2026/01/29/youtube-ai-slop-channel-crackdown-bans/))
- **YouTube does not ban AI or faceless formats.** It labels synthetic content without penalising reach and promotes its own generative tools; the stated line is originality and value, not technology. A carefully edited, genuinely useful AI-assisted channel is permitted. ([YouTube Help 1311392](https://support.google.com/youtube/answer/1311392?hl=en); [mediacopilot.ai](https://mediacopilot.ai/youtube-purging-ai-slop-channels-creators-ai-tools/))
- **The vidIQ numbers are associations and stock figures.** 30.8% of weekly uploaders reaching 1,000 subscribers within a year is not the success rate of a deliberate, researched channel; 40.6% of channels with at least one subscriber have 1,000+. A competent operator will beat the population average. That argues for a small, measured test, not for dismissing the channel entirely.
- **RPM data comes from an MCN's client base** (AIR Media-Tech), which skews towards established channels; new-channel RPM may be lower or higher by niche. Other trackers quote Shorts RPM as low as $0.01-$0.07.
- **Enforcement counts are inconsistent** (11+6, 16, "at least 18"; one outlier claims 18,000 channels). The widely repeated "35M subscribers / 4.7B views / $10M" aggregate could not be traced to a primary statement; some blogs date the purge to April 2026.
- **Affiliate benchmarks are vendor statistics** with unclear samples; my per-1,000-view ranges inherit that weakness.
- **Search extracts mention model names I cannot independently confirm** ("Gemini 3.8 Flash", "Gemini 4 Argon", "Gemini Omni Flash", "Nano Banana 2 Lite"); the Omni Flash / Nano Banana 2 Lite pair is from an official Google blog URL, the others from secondary blogs.
- **Free consumer tools change the cost picture for a hand-operated channel** (Flow's daily credits, YouTube's in-app Veo), but they are not automatable through an API and carry watermark or commercial-use limits, so they do not rescue the *autonomous* model.
- **All pricing is volatile**: Sora disappeared within a year of launch; Amazon and X changed their programmes mid-2026. Any spreadsheet built on these numbers has a short shelf life.
- **Everything here was obtained through search extracts, not opened pages** (see the method limitation at the top).

## Implications for FactoryOS

1. **Do not make ad-monetised AI channels the path to first revenue.** With today's facts the median outcome over 12 months is $0, the realistic first platform dollar is 9-18 months away, the bar doubles in 76 days, and the format that fits "zero additional spend" is the one YouTube names as ineligible. This is the slowest and least controllable of the options on the table.
2. **The owner's own invariants already rule out the farm.** Mandatory human approval before publishing plus zero spend means FactoryOS cannot be a high-volume autonomous publisher. Keep those invariants; drop the farm framing.
3. **Reposition the Content Factory as a marketing and lead-generation engine for something that is sold.** One real customer for a paid offer (a MyCast/MyBrief subscription, or a done-for-you content/automation service for a small business) is worth more than a year of ad revenue from a channel that barely clears the threshold (~$280-$550 a year). Measure content by enquiries and sign-ups, not views.
4. **If a channel is run at all, run exactly one, as an option with a kill rule.** Long-form, English, a niche where the founder has first-hand material (building an autonomous AI company in public is one), the founder's own voice or a consistent narrated perspective, 2-3 uploads a week, zero paid generation. Review at day 30 and day 60 against the watch-hours-per-day and enquiries metrics in section 7; stop or keep it purely as a marketing asset if the ad route is refuted.
5. **Do not build multi-channel orchestration, generated-video pipelines or Shorts volume features now.** Shorts were under 2% of revenue for most monetised channels, TikTok pays nothing to a Ukrainian account, and X requires a paid subscription. Engineering time spent there has no revenue path.
6. **Treat affiliate as a supplement that can start immediately on purchase-intent content** (tool comparisons the founder actually uses), with disclosure in the video and description. Expect single or double digits a month until traffic exists.
7. **Ranking for speed to first payment and durability (my judgment):** (1) a service sold directly to a business - first payment possible in weeks, depends only on finding one buyer; (2) a narrow paid product with content as its funnel - weeks to months, durable if retention exists; (3) affiliate on purchase-intent content - months, small; (4) ad-monetised automated channels - 9-18 months, low probability, revocable by a policy update. The content farm is last on both speed and durability.
8. **Before any spend decision, re-open these pages directly:** YouTube Help 72851 (thresholds and the 2027 change), 1311392 (inauthentic content), 7101720 (Ukraine availability), Google's Veo pricing, and the FTC endorsement guidance.

## Sources

No page could be opened in full in this session (WebFetch blocked for every host; see the method limitation). The list below is every page whose content was returned by the search tool and used above.

Official pages (content returned by domain-restricted or explicitly attributed search)
- https://support.google.com/youtube/answer/72851?hl=en - YPP overview and eligibility, including the 1 February 2027 change
- https://support.google.com/youtube/answer/13429240?hl=en - expanded YPP overview
- https://support.google.com/youtube/answer/1311392?hl=en - channel monetisation policies (inauthentic and reused content)
- https://support.google.com/youtube/answer/2801973?hl=en - spam policy
- https://support.google.com/youtube/answer/7101720?hl=en - YPP availability by country
- https://support.google.com/adsense/answer/13402307?hl=en - AdSense availability
- https://support.google.com/youtube/answer/14328491?hl=en - disclosing altered or synthetic content
- https://support.google.com/youtube/answer/15447836?hl=en - "How this content was made" disclosures
- https://blog.youtube/news-and-events/disclosing-ai-generated-content/
- https://blog.youtube/news-and-events/improving-ai-labels-viewers-creators/
- https://developers.google.com/youtube/v3/revision_history?hl=en - YouTube Data API revision history
- https://www.tiktok.com/creator-academy/en/article/creator-rewards-program
- https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en
- https://help.x.com/en/using-x/creator-revenue-sharing
- https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation
- https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/image-generation
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-omni-flash-nano-banana-2-lite/
- https://discuss.ai.google.dev/t/veo-3-video-model-api-pricing/106415

Press and research
- https://www.tubefilter.com/2026/01/29/youtube-ai-slop-channel-crackdown-bans/
- https://www.tubefilter.com/2026/08/10/youtube-partner-program-ad-eligibility-requirements-shorts/amp/
- https://www.hollywoodreporter.com/business/digital/faceless-creators-youtube-ai-damage-1236617586/
- https://thenextweb.com/news/youtube-ai-slop-crackdown-faceless-creators-collateral-damage
- https://www.cnbc.com/2026/01/21/youtube-chief-says-managing-ai-slop-is-a-priority-for-2026-.html
- https://fortune.com/2026/04/01/ai-slop-200-organizations-letter-youtube-google/
- https://www.kapwing.com/blog/ai-slop-report-the-global-rise-of-low-quality-ai-videos/
- https://www.searchenginejournal.com/youtubes-ai-slop-problem-and-how-marketers-can-compete/567297/
- https://www.techtimes.com/articles/320629/20260715/youtube-wiped-35m-subscribers-over-ai-slop-now-its-judging-your-taste.htm
- https://www.gizchina.com/youtube/youtube-removes-major-ai-slop-channels-after-study-reveals-billions-of-views
- https://www.digitalcameraworld.com/tech/artificial-intelligence/youtube-gets-tough-on-ai-slop-ruining-the-party-for-million-dollar-brain-rot-video-channels
- https://dig.watch/updates/youtube-enlists-users-to-rate-videos-as-ai-slop-in-content-quality-push
- https://dailydot.com/youtube-prompt-asking-does-this-feel-like-ai-slop
- https://mediacopilot.ai/youtube-purging-ai-slop-channels-creators-ai-tools/
- https://ppc.land/new-youtube-creators-face-8-000-hour-bar-for-ad-revenue-from-february-2027/
- https://techcrunch.com/2024/02/28/telegram-is-launching-ad-revenue-sharing-next-month-using-toncoin
- https://dev.ua/en/news/facebook-uvimknuv-monetyzatsiiu-ukraintsiam-1770808882
- https://hi-tech.ua/en/ukrainian-users-will-be-able-to-monetize-pages-with-5000-followers-on-facebook/
- https://komersant.ua/en/yak-zaroblyati-v-tiktok-v-ukraini-perevireni-sposobi-monetizaczii/
- https://ukranews.com/en/news/1125233-algorithms-promote-ai-garbage-low-quality-content-flooded-youtube-and-brings-in-hundreds-of-millions

Vendor datasets and guides (treat as vendor or secondary)
- https://vidiq.com/research/youtube-uploads-1000-subscribers/
- https://vidiq.com/research/youtube-subscriber-benchmarks-2026/
- https://vidiq.com/blog/post/youtube-subscriber-growth-statistics/
- https://vidiq.com/blog/post/youtube-partner-program-changes-2027/
- https://vidiq.com/blog/post/non-u-s-creators-24-percent-tax-youtube-revenue/
- https://air.io/en/monetization/what-rpm-can-you-expect-from-shorts-in-2026
- https://air.io/en/air-data-findings/youtube-monetization-statistics-2026
- https://air.io/en/air-data-findings/which-youtube-niche-makes-the-most-money-in-2026-ranked-by-real-rpm-and-cpm
- https://air.io/en/youtube-hacks/should-you-chase-shorts-views-or-double-down-on-long-form-for-channel-growth
- https://air.io/en/trending/youtube-updates-its-monetization-rules-what-creators-need-to-know
- https://air.io/en/monetization/comparing-shorts-monetization-to-tiktok-creator-rewards
- https://air.io/en/monetization/youtube-partner-program-requirements-2026-the-complete-guide
- https://mubert.com/blog/youtube-rpm-by-niche-and-country
- https://www.overseeros.com/blog/youtube-rpm-by-niche
- https://fluxnote.io/guides/youtube-shorts-rpm-by-country
- https://fluxnote.io/guides/youtube-tax-withholding-w8ben-2026
- https://miraflow.ai/blog/youtube-shorts-rpm-2026-real-ranges-by-niche
- https://www.teleprompter.com/blog/vlogging-statistics
- https://outlierkit.com/resources/youtube-partner-program-changes-2027/
- https://www.tubebuddy.com/blog/youtube-ai-demonetization-how-to-spot-risk/
- https://mateostarcevicfilipovic.medium.com/youtube-quietly-demonetizes-faceless-ai-channels-since-july-2025-30b3d2daaf2e
- https://medium.com/@automation.labs/faceless-ai-youtube-pays-50k-a-month-most-lose-money-9120e2906541
- https://monetizednow.com/creator-rewards-countries
- https://spilnoagency.com.ua/en/instructions-us/monetization-on-tiktok-how-it-works
- https://contentmonetizing.com/en/how-to-get-facebook-monetization/
- https://contentmonetizing.com/en/youtube-monetization-countries/
- https://insighthive.app/resources/facebook-content-monetization-eligible-countries
- https://opentweet.io/blog/x-original-content-rewards-2026
- https://climbx.so/blog/x-original-content-rewards-3m-impressions
- https://xpert.so/blog/how-much-does-x-actually-pay-creators-in-2026-34363
- https://nlosmm.com/blog/how-much-can-you-earn-from-x-twitter-2026
- https://tguard.pro/en/blog/telegram-channel-monetization-eligibility/
- https://wecantrack.com/insights/youtube-affiliate-marketing-statistics/
- https://www.trackrev.io/blog/link-tracking-benchmarks-2026
- https://www.zebracat.ai/post/youtube-affiliate-marketing-statistics
- https://influencerfee.com/blog/youtube-influencer-affiliate-rates/
- https://getlasso.co/amazon-affiliate-commission-rate/
- https://www.shopifreaks.com/amazon-quietly-slashed-associates-affiliate-commission-rates-by-up-to-50-across-publisher-ecosystem-and-gutted-reporting-tools/
- https://www.karooya.com/blog/amazon-affiliate-commission-cuts-2026-what-changed-and-what-it-means-for-advertisers/
- https://invideo.io/blog/ai-video-model-pricing/
- https://apiframe.ai/blog/ai-video-api-pricing-2026
- https://apiframe.ai/guides/runway-api-guide
- https://www.cloudzero.com/blog/kling-ai-pricing/
- https://www.teamday.ai/blog/best-ai-video-models-2026
- https://www.cartesia.ai/learn/elevenlabs-pricing
- https://www.cloudzero.com/blog/elevenlabs-pricing/
- https://dev.to/hassann/gemini-api-free-tier-in-2026-limits-models-and-when-you-get-billed-4081
- https://thehype.news/best-free-ai-video-generator/
- https://www.revid.ai/blog/ai-youtube-shorts
