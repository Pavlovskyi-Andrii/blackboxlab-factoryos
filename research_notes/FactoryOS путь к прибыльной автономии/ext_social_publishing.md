# Social publishing and analytics routes for FactoryOS (state as of 17 November 2026)

Researcher scope: official publishing/analytics APIs (YouTube, Instagram, Facebook, Threads, TikTok, LinkedIn, X), third-party publishing providers, platform rules on automation and AI content.

**Read this first - evidence quality.** In this session `WebFetch` was blocked by the network policy for every host tried (`developers.google.com`, `developers.facebook.com`, `developers.tiktok.com`, `docs.x.com`: proxy answered 403 to CONNECT). No page could be opened in full. Everything below comes from `WebSearch` result summaries; for official facts the search was restricted to the official domain, so the text is the official page as surfaced by the search tool, not a full page read. The shared web-search budget also ran out before five planned checks (listed under Gaps). Labels used on every fact:

- **[P]** official page text returned by a domain-restricted search (official domain). One step weaker than a full page read.
- **[S]** secondary source (press, third-party blog) returned by search.
- **[V]** vendor's own claim about its own product or a competitor (many "pricing guides" are written by competing vendors such as Blotato, Upload-Post, Zernio - treat as marketing).
- **[T]** my training recollection (knowledge cutoff mid-2026), not re-verified today.
- **[R]** fact read in the FactoryOS repository today.
- **[I]** my inference.

In the Key claims table, `verified_primary` means **[P]** (official text via search, not a full page read).

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | YouTube Data API is free. Since 1 June 2026 uploads sit in their own quota bucket: `videos.insert` costs 1 unit there, default 100 upload calls/day, plus 100 `search.list` calls/day and 10,000 units/day for all other methods. (The cost had already fallen from ~1,600 to ~100 units on 4 Dec 2025; the old "6 uploads a day" figure is obsolete.) | https://developers.google.com/youtube/v3/docs/videos/insert ; https://developers.google.com/youtube/data/getting-started ; https://developers.google.com/youtube/data/revision_history | 4 Dec 2025 and 1 Jun 2026 entries | verified_primary |
| 2 | The rule that uploads from unverified API projects (created after 28 Jul 2020) are locked to private is reported as reversed: the official revision history is summarised as saying such uploads "are no longer restricted to private viewing mode" (entry dated 2 Nov 2026 in one of two search passes). Other copies of the docs still carry the 2020 wording. Not confirmed by a page read or a test upload. | https://developers.google.com/youtube/data/revision_history | 2 Nov 2026 (date from one search pass only) | reported_secondary |
| 3 | A Google OAuth app left in "Testing" status loses its refresh token 7 days after consent (non-basic scopes such as `youtube.upload`); the fix is publishing status "In production" and re-consent. | https://support.google.com/cloud/answer/10311615 | retrieved 17 Nov 2026 | verified_primary |
| 4 | Meta: an app that publishes only to Instagram accounts the developer owns or manages needs Standard Access only - App Review and Business Verification are not required. Advanced Access is needed only to serve other people's accounts. | https://developers.facebook.com/documentation/instagram-platform/app-review ; https://developers.facebook.com/docs/graph-api/overview/access-levels | retrieved 17 Nov 2026 | verified_primary |
| 5 | Meta publishing caps per rolling 24 h: Instagram 50 API-published posts in the reference pages (the main guide says 100; query `content_publishing_limit` for the live value), 400 containers; Facebook Page Reels 30; Threads 250. All free. | https://developers.facebook.com/docs/instagram-platform/content-publishing/ ; https://developers.facebook.com/documentation/video-api/guides/reels-publishing ; https://developers.facebook.com/documentation/threads/overview | retrieved 17 Nov 2026 | verified_primary |
| 6 | TikTok Content Posting API: an unaudited client can post only privately (SELF_ONLY), for at most 5 users per 24 h, and the posting accounts must be private. Public posting needs a TikTok audit. Audited clients get roughly 15 posts/day per creator, shared across all API clients. | https://developers.tiktok.com/docs/en/content-sharing-guidelines ; https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post | docs ~3.5 months old at indexing | verified_primary |
| 7 | Self-hosting Postiz (AGPL-3.0, free) does not remove platform gates: you register your own developer app on each network, and Postiz forces TikTok posts to SELF_ONLY until your own TikTok app is audited. A user-filed issue reports a Direct Post audit failing because the generic composer did not meet TikTok's required UX. | https://docs.postiz.com/providers/tiktok ; https://github.com/gitroomhq/postiz-app/issues/1362 | retrieved 17 Nov 2026 | verified_primary (docs); anecdotal (issue) |
| 8 | LinkedIn: `w_member_social` (post as the member) is an open permission via "Share on LinkedIn". Company-page posting and analytics need the Community Management API: Development tier is capped at 500 calls/app/day and 100/member/day, needs a screencast to reach Standard tier and must be upgraded within 12 months. Reading member posts (`r_member_social`) is closed to new applicants. | https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06 ; https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access | li-lms-2026-06 to 2026-10 | verified_primary |
| 9 | X API is pay-per-use with prepaid credits. Since 20 Apr 2026: $0.015 per post created, $0.20 per post that contains a URL, $0.005 per post read, $0.001 per owned read, $0.010 per user read. No free tier for new developers (legacy Free users got a one-time $10 voucher). | https://devcommunity.x.com/t/x-api-pricing-update-owned-reads-now-0-001-other-changes-effective-april-20-2026/263025 ; https://devcommunity.x.com/t/announcing-the-x-api-pay-per-use-pricing-pilot/250253 | 20 Apr 2026 | verified_primary (rates); reported_secondary (no free tier) |
| 10 | Metricool: the REST API exists only on Advanced and Custom plans (Advanced from $53/month billed annually, $67 monthly). The Metricool MCP works on every plan including Free, but plan limits apply - Free cannot schedule more than 20 posts per month. | https://help.metricool.com/plans-add-ons-and-api-access-explained-xux1u ; https://help.metricool.com/mcp-limits-and-plan-requirements-h72jg ; https://metricool.com/premium-vs-free-metricool-plans/ | help pages retrieved 17 Nov 2026; price checked in repo audit 1 Nov 2026 | verified_primary |
| 11 | Third-party posting APIs, entry prices (mostly vendor or competitor pages): Zernio - first 2 accounts free, $6/account for accounts 3-10; Upload-Post - free 10 uploads/month and 2 profiles, paid from $16-24/month; Buffer - API key on every plan incl. Free (3 channels, 3,000 requests/30 days); Postiz cloud $29/month; Blotato $29/month, no free API; Ayrshare $149/month for one profile. | https://www.blotato.com/blog/ayrshare-pricing ; https://www.upload-post.com/best-social-media-apis/ ; https://zernio.com/blog/buffer-api ; https://postiz.com/ | Jul-Nov 2026 pages | vendor_claim |
| 12 | YouTube monetisation: since 15 Jul 2025 the "inauthentic content" policy makes repetitive or mass-produced content ineligible, including "AI-generated content made with generic or unoriginal templates". AI use itself is allowed. A July 2026 clarification reportedly names three non-monetisable groups: generic/template-based, unsatisfying/off-putting, and AI personas giving advice on sensitive topics. | https://support.google.com/youtube/answer/1311392 ; https://www.tubefilter.com/2026/07/13/youtube-inauthentic-content-monetization-policy-update/ | 15 Jul 2025; 13-16 Jul 2026 | verified_primary (2025 policy); reported_secondary (2026 clarification) |
| 13 | Enforcement is real: on 18 Dec 2025 YouTube terminated the AI fake-trailer channels Screen Culture and KH Studio (2M+ subscribers combined) for spam and misleading metadata after an earlier monetisation suspension. A secondary source reports 16 of the top 100 "AI slop" channels gone by Jan 2026 (11 terminated, 5 wiped). | https://deadline.com/2025/12/youtube-fake-movie-trailers-celebrate-hollywood-studios-1236653577/ ; https://www.thewrap.com/industry-news/tech/youtube-terminates-screen-culture-kh-studio-over-ai-fake-movie-trailers/ | Dec 2025; Jan 2026 | reported_secondary |
| 14 | Meta: accounts that repeatedly reuse others' content lose monetisation for a period and get reduced distribution on everything they post; unoriginal content "without meaningful enhancements" cannot be monetised; about 500,000 accounts were actioned in H1 2025. "AI info" labels are informational, not a monetisation penalty by themselves. | https://creators.facebook.com/blog/combating-unoriginal-content ; https://en-gb.facebook.com/business/help/169845596919485 ; https://transparency.meta.com/governance/tracking-impact/labeling-ai-content/ | Jul 2025 onward | verified_primary |
| 15 | TikTok requires a label on realistic AI-generated content; unlabelled content may be removed, restricted or labelled by TikTok. The Direct Post API has an `is_aigc` flag that applies the "Creator labeled as AI-generated" tag. | https://www.tiktok.com/safety/en/policies-and-engagement/integrity-authenticity ; https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post | retrieved 17 Nov 2026 | verified_primary |

## Detailed findings

### 1. YouTube (Data API v3, Analytics API, Shorts)

**Cost and quota**
- [P] Default allocation: "100 search.list calls, 100 videos.insert calls, and 10,000 units per day combined for all other endpoints"; the default is "subject to change". https://developers.google.com/youtube/data/getting-started
- [P] `videos.insert`: "A call to this method has a quota cost of 1 unit in the Video Uploads quota bucket"; quota impact 100 calls per day. https://developers.google.com/youtube/v3/docs/videos/insert
- [P] Revision history: the API "is transitioning to a granular quota system covering smaller sets of methods, starting with videos.insert and search.list" (effective 1 June 2026); earlier entry (4 Dec 2025): upload cost changed "from approximately 1600 units to approximately 100 units". https://developers.google.com/youtube/data/revision_history
- [P] The Quota Calculator page is reported as still showing 1,600 units - a stale copy. https://developers.google.com/youtube/v3/determine_quota_cost
- [S] Third-party guides agree on "100 uploads/day, not 6 any more". https://repostit.io/youtube-api-daily-limit/ ; https://dev.to/aipredictions_dev/youtube-now-counts-uploads-in-their-own-bucket-100-a-day-one-unit-each-29gm
- [P] More quota is requested through the Quota Extension Form, which involves a compliance audit; Google also "runs periodic audits" of API clients. https://developers.google.com/youtube/data/guides/quota_and_compliance_audits ; https://developers.google.com/youtube/terms/developer-policies
- [I] At 1-3 uploads a day FactoryOS uses 1-3% of the upload bucket. Quota is not a constraint and no quota-extension audit is needed.

**The "locked private" rule**
- [P, date uncertain] The official revision history is summarised by the search tool as stating that videos uploaded through `videos.insert` from unverified API projects "are no longer restricted to private viewing mode", reversing the 28 July 2020 policy. One search pass dated the entry 2 November 2026; a second pass confirmed the content but not the date. https://developers.google.com/youtube/data/revision_history
- [P] Conflict inside Google's own docs: at least one copy of the Videos resource page still says uploads from unverified projects created after 28 July 2020 "will be restricted to private viewing mode". https://developers.google.com/youtube/v3/docs/videos?hl=en
- [P] Help page for creators whose videos were locked: https://support.google.com/youtube/answer/7300965
- [S] Most 2026 third-party guides still describe the lock (they may be out of date). https://www.upload-post.com/youtube-api/
- [R] FactoryOS `DECISIONS.md` (15 Nov 2026, T-552-YT) still assumes "Google also forces uploads from unaudited API projects to private". If the November entry is real, this assumption is two weeks out of date.
- [I] This is the single most decision-relevant unverified fact in these notes. It is cheap to settle: one owner-approved upload with `privacyStatus=public`, then read back `status.privacyStatus`.

**OAuth failure mode**
- [P] In "Testing" publishing status, "authorizations by a test user will expire seven days from the time of consent", including the refresh token when offline access is requested. https://support.google.com/cloud/answer/10311615
- [S] The exception covers only basic scopes (email, profile, openid); `youtube.upload` is not one. https://nango.dev/docs/api-integrations/youtube/how-to-register-your-own-youtube-api-oauth-app
- [S, anecdotal] Forum reports: switching to "In production" without completing verification and re-authorising stopped the weekly expiry. https://community.n8n.io/t/youtube-refresh-token-expired/5319
- [T] An unverified production app shows an "unverified app" warning at consent and is capped at 100 users; irrelevant when the only user is the owner.

**Analytics**
- [P] `yt-analytics.readonly` gives `reports.query` access to non-monetary metrics (views, ratings) for the authorising user's channel (`ids=channel==MINE`); revenue metrics need the separate `yt-analytics-monetary.readonly` scope. https://developers.google.com/youtube/reporting/guides/authorization
- [Gap] The quota cost of Analytics API calls was not found.

**Shorts**
- [R, from Metricool help, 1 Nov 2026] A Short is a vertical or square video up to 3 minutes; there is no separate Shorts endpoint - it is an ordinary upload. Source in repo audit: https://help.metricool.com/schedule-and-publish-on-youtube-gof0k
- [Gap] Google's own page on Shorts classification via API was not reached.

**AI disclosure**
- [P] `status.containsSyntheticMedia` (boolean, added October 2024) can be set in `videos.insert` / `videos.update`. https://developers.google.com/youtube/data/revision_history
- [P] Disclosure is required for realistic altered or synthetic content (a person saying or doing something they did not, a fabricated realistic event). It is not required for clearly unrealistic or animated content or when AI only assisted production (scripts, ideas). Undisclosed content may get a label the creator cannot remove. Disclosure "won't limit a video's audience or affect monetization eligibility". https://support.google.com/youtube/answer/14328491
- [R] FactoryOS sets `containsSyntheticMedia: true` on every upload - safe, slightly over-inclusive.

### 2. Meta: Instagram, Facebook Pages, Threads

**Access for a solo operator**
- [P] "If your app only serves your Instagram professional account or an account you manage, Standard Access is all your app needs"; the App Review guide lists "My app is only for a business I own or manage" as App Review not required. https://developers.facebook.com/documentation/instagram-platform/app-review
- [P] Standard Access permissions "can only be requested from app users who have a role on the requesting app". https://developers.facebook.com/docs/graph-api/overview/access-levels
- [P] Permissions: Instagram Login - `instagram_business_basic` + `instagram_business_content_publish`; Facebook Login - `instagram_content_publish` plus Page read permissions. If the linked Page requires Page Publishing Authorization, it must be completed first. https://developers.facebook.com/docs/instagram-platform/content-publishing/
- [P] Requires an Instagram professional account. [S] One vendor guide says Reels publishing works only for Business accounts, not Creator accounts - conflicts with Metricool's help (Business/Creator); unverified. https://postproxy.dev/blog/instagram-reels-api-publishing-guide/
- [T] Media must be reachable by Meta at a public URL at publish time (Meta fetches it), which interacts with FactoryOS's signed-media boundary. Posts made by a Facebook app in Development mode may be visible only to people with a role on the app, so the app should be Live with Standard Access. Both points need a test.

**Limits**
- [P] Instagram: main guide - 100 API-published posts per 24-hour moving period; carousel section, publish endpoint reference and `content_publishing_limit` reference - 50. Carousels count as one. 400 containers per rolling 24 h; containers expire after 24 h. Check live usage with `GET /<IG_ID>/content_publishing_limit`. https://developers.facebook.com/docs/instagram-platform/content-publishing/ ; https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit.md
- [P] Facebook Page Reels: permissions `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`; Page token from a user with the CREATE_CONTENT task; three-step upload; 3-90 seconds, 24-60 fps, 1080x1920 recommended; 30 API-published Reels per rolling 24 h. https://developers.facebook.com/documentation/video-api/guides/reels-publishing
- [P] Threads: 250 API-published posts per rolling 24 h per profile; check `threads_publishing_limit`; permission `threads_content_publish` (depends on `threads_basic`), intended for apps publishing to the user's own profile. https://developers.facebook.com/documentation/threads/overview ; https://developers.facebook.com/docs/permissions

**Analytics**
- [P] Facebook video and Reels insights need `read_insights` (plus `pages_manage_engagement`); data only for the past two years. https://developers.facebook.com/docs/graph-api/reference/video/video_insights/
- [P] Threads exposes views, likes, replies, reposts, quotes and follower counts at media and account level. https://developers.facebook.com/blog/post/2024/06/18/the-threads-api-is-finally-here/
- [Gap] Current Instagram insights metric names and permission were not re-verified today.

### 3. TikTok

- [P] "Unaudited clients can only post content in private mode"; lifting it needs an audit confirming Terms of Service compliance. Public attempt returns `unaudited_client_can_only_post_to_private_accounts`. https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- [P] Unaudited clients: up to 5 users posting per 24 h; every account must be private at the time of posting; at most 5 pending shares per 24 h. Audited clients: per-creator cap "typically around 15 posts a day", shared across all Direct Post clients, plus a creator cap based on the audit application. https://developers.tiktok.com/docs/en/content-sharing-guidelines
- [S] App Review (grants `video.publish`) and the Content Posting audit are two separate gates; vendor blogs quote 2-6 weeks, a figure not found in TikTok's docs. https://adaptlypost.com/blog/why-does-my-app-need-approval-post-tiktok
- [P] `post_info.is_aigc` (bool): "Set to true if the video is AI generated content"; adds the "Creator labeled as AI-generated" tag. https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- [P] Display API (analytics, read-only): scope `video.list` - the user's public videos, max 20 per page; scope `user.info.stats` - likes, follower, following and video counts. Requires Login Kit approval. https://developers.tiktok.com/docs/en/tiktok-api-scopes ; https://developers.tiktok.com/docs/en/display-api-get-started
- [T, not re-verified - search budget ran out] TikTok's app review guidelines reject apps meant for personal or internal company use and require a public website and the prescribed posting UX (privacy selector, consent text, commercial-content toggle). If so, a private FactoryOS tool is unlikely to pass the audit.
- [T, not re-verified] The "upload to inbox/draft" mode (`video.upload` scope) sends the video to the creator's TikTok inbox, and the creator finishes the post in the app. Whether this mode escapes the private-only restriction for unaudited clients was not confirmed.

### 4. LinkedIn

- [P] `w_member_social` - "Post, comment and like posts on behalf of an authenticated member" - is an open permission under the Share on LinkedIn product. https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- [P] Community Management API: every app starts in Development tier (500 calls per app and 100 per member per 24 h, no BATCH_GET, no social-action webhooks). Standard tier needs a screencast of each use case; upgrade is required within twelve months or access is removed. The product must be the only product on the developer application. https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06 ; https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-09
- [P] `r_member_social` is "a closed permission. We're not accepting access requests at this time". https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- [P] Posts API docs are versioned monthly (`li-lms-2026-10` seen today). https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-10
- [S] LinkedIn's API terms are summarised as barring use of the APIs "to automate posting", while the open permission grants posting on a member's behalf; the exact scope is unclear. https://www.blotato.com/research/social-media-automation-rulebook
- [T, not re-verified] The Community Management API is granted to registered legal entities with a verified company page, not to individuals.
- [I] For a solo founder: member posting is possible and free; member-post analytics through the API is effectively unavailable; company-page automation carries an application burden that is not justified before there is an audience.

### 5. X

- [P] Pay-per-use, credits bought in advance and drawn down per request. https://docs.x.com/x-api/introduction
- [P] From 20 April 2026: `POST /2/tweets` $0.015 per post; posts containing a URL $0.20; summoned replies $0.01; owned reads $0.001. Pilot rates: post read $0.005, user read $0.010; expansion objects billed at the same per-resource rates. https://devcommunity.x.com/t/x-api-pricing-update-owned-reads-now-0-001-other-changes-effective-april-20-2026/263025 ; https://devcommunity.x.com/t/inform-x-api-ppu-expansions-update/279110
- [P] Recently active Legacy Free users got a one-time $10 voucher. https://devcommunity.x.com/t/announcing-the-x-api-pay-per-use-pricing-pilot/250253
- [P vs S conflict] The X changelog says Basic and Pro remain available and existing subscribers can opt in to pay-per-use (https://docs.x.com/changelog); third-party guides say Basic ($200/month) and Pro ($5,000/month) are closed to new users and Basic subscribers were moved to pay-per-use from 1 June 2026 (https://postproxy.dev/blog/x-api-pricing-2026/). Unresolved.
- [S, anecdotal] Developers report media uploads billed as an extra Post: Create event (about $0.030 for a post with media) and one over-charging case. https://devcommunity.x.com/t/undocumented-postcreate-usage-for-media-uploads-please-clarify-pay-per-use-billing/274646 ; https://devcommunity.x.com/t/pay-per-use-billing-issue-overcharged-20x-per-post/263811
- [I] Cost range, assuming 1 post/day: $0.45/month without links, about $0.90 with media if the anecdote holds, $6.00/month if every post carries a link. Reading own metrics daily for 30 posts is about $0.90/month. Small, but it is a prepaid paid API, so it conflicts with "zero additional spend" unless the owner approves.

### 6. Third-party publishing providers

Prices are entry prices in USD per month. Most rows rest on vendor or competitor pages; none was confirmed on the vendor's own pricing page today.

| Provider | Free route | Cheapest paid API route | Notes | Source and label |
|---|---|---|---|---|
| Metricool | MCP on every plan; Free limited to 20 scheduled posts/month | REST API only on Advanced: $53 (annual) / $67 (monthly), up to 15 brands | Owner already has it connected to Instagram, TikTok, YouTube [R]. Daily limits: Instagram 50/24 h; YouTube 10/24 h on Free, 20 on paid [R, help page 1 Nov 2026]. MCP is a client for an AI assistant, not a server-to-server API. | https://help.metricool.com/plans-add-ons-and-api-access-explained-xux1u ; https://help.metricool.com/mcp-limits-and-plan-requirements-h72jg ; https://help.metricool.com/faqs-about-the-metricool-mcp-1i3w0 [P] |
| Buffer | Free plan: 3 channels, 10 scheduled posts per channel at a time, 1 API key, 3,000 requests/30 days | Essentials $5 per channel (3 keys, 7,500 requests) | GraphQL API launched 27 May 2026, described as public beta by one source and GA by another; analytics not included or experimental. | https://zernio.com/blog/buffer-api ; https://www.postzen.dev/blog/buffer-api [V - competitor pages] |
| Zernio (formerly Late) | First 2 connected accounts free, unlimited posts, full API | $6 per account for accounts 3-10 | Per-account pricing since May 2026; X costs passed through; an older Zernio changelog page describes 2 profiles / 10 posts a month. | https://lokeshkapoor.com/blog/zernio-review ; https://zernio.com/changelog/simplified-pricing-plans-for-late-api-users [S/V, conflicting] |
| Upload-Post | 10 uploads/month, 2 profiles, API included | $24 monthly / $16 annual, unlimited posts, 5 profiles | One review says TikTok uploads return 403 on the free plan. | https://www.upload-post.com/best-social-media-apis/ ; https://www.linkstartai.com/en/agents/upload-post [V] |
| Postiz | Self-hosted, AGPL-3.0, free | Cloud from $29 ($23 annual) | Self-hosting needs your own developer app per network; TikTok forced SELF_ONLY until your app is audited. | https://postiz.com/ ; https://docs.postiz.com/providers/tiktok [P for docs, V for price] |
| Blotato | None (7-day trial excludes API) | Starter $29 | Generating an API key starts the paid plan. | https://www.blotato.com/research/social-media-agent-pricing [V] |
| Ayrshare | None (28-day trial on Launch) | Premium $149 for one profile; Launch $299 for 10 profiles | Priced for SaaS builders, not solo creators. | https://www.blotato.com/blog/ayrshare-pricing ; https://www.upload-post.com/ayrshare-pricing/ [V - competitor pages] |
| vidIQ | MCP "free on every vidIQ plan, including Free" (launch period, no end date published) | Plan prices conflict across review sites ($19-49/month) | Reviews describe it as research and data. The vidIQ MCP connected to this session lists tools named `vidiq_video_upload`, `vidiq_social_post_publish`, `vidiq_instagram_publish_reel` - observed in the tool list, not invoked; limits and plan requirements unknown. Calls reportedly cost credits (about 5 per call). | https://vidiq.com/mcp/ ; https://outlierkit.com/resources/vidiq-mcp/ [V/S] |

**Which route gives legal multi-network posting at the lowest cost?** [I]
- $0, most durable: official APIs for the founder's own accounts - YouTube (free, 100 uploads/day), Instagram + Facebook Page + Threads under Meta Standard Access (no App Review), LinkedIn personal profile via Share on LinkedIn.
- TikTok is the exception: a private tool cannot post publicly through its own unaudited app. $0 options are an aggregator that holds an audited TikTok app (Metricool Free, 20 posts/month across all networks; Buffer Free; Zernio's free two accounts; Upload-Post's 10 uploads) or the owner posting by hand, which the approval gate already requires in spirit.
- X is the only network with a per-post charge on the official route.
- If one paid vendor is ever justified, the low end is $5-29/month (Buffer per channel, Zernio per account, Upload-Post, Postiz cloud, Blotato). Metricool Advanced ($53-67) and Ayrshare ($149) are not justified at zero revenue.

### 7. Platform rules on AI-generated and mass-produced content

**YouTube**
- [P] 15 July 2025: "repetitious content" renamed "inauthentic content", clarified to include "content that is repetitive or mass-produced"; "This type of content has always been ineligible for monetization." Reused-content policy unchanged. https://support.google.com/youtube/answer/1311392
- [P] Ineligible examples: "image slideshows, templated storylines, or scrolling text with minimal or no narrative, commentary, or educational value"; "AI-generated content made with generic or unoriginal templates". Allowed: a repeated format where "the substance of each video should be materially varied". https://support.google.com/youtube/answer/1311392
- [P] The policy applies to the whole channel; monetisation can be removed channel-wide. Channels using AI remain eligible if the content is clearly original. https://support.google.com/youtube/community-guide/271248162
- [P] Spam policy separately covers using automated tools or AI to produce high volumes of similar content with minimal changes; violations can lead to strikes or termination. https://support.google.com/youtube/answer/2801973
- [S] July 2026 clarification: non-monetisable groups are generic or template-based content, unsatisfying or off-putting content, and AI personas presented as human experts giving health, finance, legal or political advice; "channels uploading this content will not be allowed to monetize". Dates in coverage vary between 9 and 16 July 2026; the official help page text was not retrieved. https://www.tubefilter.com/2026/07/13/youtube-inauthentic-content-monetization-policy-update/ ; https://www.androidheadlines.com/2026/07/youtube-monetization-rules-ai-slop-inauthentic-content.html
- [S] Enforcement: Screen Culture and KH Studio terminated on 18 Dec 2025 - after being let back into monetisation "they reverted to clear violations of our spam and misleading metadata policies". https://deadline.com/2025/12/youtube-fake-movie-trailers-celebrate-hollywood-studios-1236653577/ ; https://www.thewrap.com/industry-news/tech/youtube-terminates-screen-culture-kh-studio-over-ai-fake-movie-trailers/
- [S, single blog] January 2026: 16 of the top 100 "AI slop" channels from a Kapwing report gone (11 terminated, 5 wiped), about 35M subscribers and an estimated $10M annual ad revenue. https://outlierkit.com/blog/youtube-ai-crackdown ; https://www.techtimes.com/articles/320629/20260715/youtube-wiped-35m-subscribers-over-ai-slop-now-its-judging-your-taste.htm
- [P] Fake engagement policy (artificially inflating views, likes, subscribers) exists as a separate policy. https://support.google.com/youtube/answer/3399767
- [P] The YouTube Partner Program is available in Ukraine. https://support.google.com/youtube/answer/7101720 [S] One third-party list says the lower 500-subscriber tier is not listed for Ukraine. https://dipak7.com.np/youtube-partner-program-countries-list/

**TikTok**
- [P] Creators "must label" realistic AI content and are encouraged to label content fully generated or significantly edited by AI; unlabelled content "may be removed, restricted, or labeled by our team". TikTok auto-labels content with C2PA credentials; an auto label cannot be removed. https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content ; https://www.tiktok.com/safety/en/policies-and-engagement/integrity-authenticity
- [S] Creator Rewards Program: 10,000 followers, 100,000 views in the last 30 days, age 18+, personal account, residence in a supported market, original videos of one minute or more; content flagged as unoriginal is excluded. https://nealschaffer.com/tiktok-creator-rewards-program/ ; https://creatorsagency.co/blog/tiktok-creator-rewards-program-2026
- [T, not re-verified] Ukraine is not among the Creator Rewards markets. The official country list was not retrieved.

**Meta**
- [P] Accounts that "improperly reuse someone else's videos, photos or text posts repeatedly will lose access to monetization programs for a period of time and receive reduced distribution on everything they share"; about 500,000 accounts actioned in H1 2025 for spammy behaviour or fake engagement. https://creators.facebook.com/blog/combating-unoriginal-content
- [P] Partner Monetisation Policies: content "that is unoriginal or reproduced without making meaningful enhancements (commentary, parody, creative editing etc.) cannot be monetised". https://en-gb.facebook.com/business/help/169845596919485
- [P] April 2025: accounts gaming distribution are not eligible for monetisation and may get lower reach. https://about.fb.com/news/2025/04/cracking-down-spammy-content-facebook/
- [P] "AI info" labels are applied when Meta detects industry-standard AI indicators or when people disclose AI content. https://transparency.meta.com/governance/tracking-impact/labeling-ai-content/ ; https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/
- [S] Facebook Content Monetization is invite-only as of October 2026; one secondary site lists Ukraine as eligible. https://monetizedyet.com/facebook-monetization-requirements/ ; https://contentmonetizing.com/en/youtube-monetization-countries/
- [Gap] No API parameter for self-declaring AI content on Instagram or Facebook posts was found.

**Consequences for a "content farm"** [I]
- The model "many templated AI videos, many channels, ad revenue" is exactly what YouTube names as non-monetisable and what its spam policy can terminate. Meta and TikTok have parallel rules.
- Platforms do not penalise AI use or honest disclosure; they penalise interchangeable, mass-produced output and misleading metadata.
- Views do not convert to revenue without programme eligibility: thresholds, originality review and, for TikTok, a supported country. For a Ukraine-based founder YouTube is the only one of the three confirmed today as available.

### 8. Browser automation and explicitly prohibited behaviour

- [P] X Automation Rules (updated April 2026): no duplicative or substantially similar posts on one account or across accounts you operate; no automated unsolicited replies or mentions, no keyword-triggered replies; automated accounts must enable the "Automated" label and name the operator. https://help.x.com/en/rules-and-policies/x-automation ; https://docs.x.com/developer-guidelines
- [T, not re-verified] X's rules also state that non-API automation, such as scripting the website, can lead to permanent suspension.
- [S] Instagram Terms of Use: no creating accounts or accessing or collecting information "in an automated way without our express permission". https://www.blotato.com/research/social-media-automation-rulebook
- [S] LinkedIn User Agreement section 8.2: no "bots or other unauthorized automated methods to access the Services". https://conductatlas.com/platform/linkedin/linkedin-user-agreement/provision/CA-P-023526/prohibition-on-bots-or-inauthentic-automated-engagement/
- [S] TikTok Terms of Service: no automated systems or "bots" to extract data without approval; Community Guidelines treat bots or scripts that inflate likes or shares as spam. https://conductatlas.com/platform/tiktok/tiktok-terms-of-service/prohibition-on-scraping-and-data-extraction/ ; https://instantdm.com/blog/is-tiktok-automation-allowed
- [S] Meta litigates against bot operators (Meta v. Social Data Trading, automated Instagram accounts). https://www.jurist.org/news/wp-content/uploads/sites/4/2021/12/Meta-Platforms-Inc.-v.-Social-Data-Trading-Ltd.pdf
- [R] The owner has already ruled out reverse-engineering private provider APIs (`.autopilot/answers.md`).
- [I] Using the FactoryOS Playwright runner to log in and post, like, follow or comment on Instagram, TikTok, LinkedIn or X breaks those terms and risks losing the account that the whole content effort depends on. Explicitly prohibited everywhere: fake engagement, multiple accounts posting the same content, fake identities.

### 9. Recommended adapter design [I]

**One interface, several routes per network**
- `capabilities()`: media types, max duration, visibility options, AI-label support.
- `validate(snapshot)`: platform limits before anything is sent (title 100 chars, Reel 3-90 s, etc.).
- `publish(snapshot, idempotency_key) -> receipt`: `platform_post_id`, URL, requested visibility, route used.
- `verify(receipt)`: read the post back and record actual visibility and processing status. This is the step that catches a silent private lock (YouTube, TikTok SELF_ONLY).
- `metrics(post_id, window)`: views, likes, comments, shares; kept separate from publishing so analytics can use a different route.
- `health()`: token age, days to expiry, remaining daily quota.

**Routes**

| Network | Primary (official, $0) | Fallback | Manual route |
|---|---|---|---|
| YouTube | Data API v3 (already built, T-552-YT) | Metricool Free via MCP or UI | YouTube Studio |
| Instagram | Graph API, Standard Access, own account | Metricool Free | Instagram app |
| Facebook Page | Pages / Reels API | Metricool Free | Meta Business Suite |
| Threads | Threads API | none needed | Threads app |
| TikTok | none for public posts without audit | Aggregator with an audited app (Metricool Free, Buffer Free, Zernio free tier) | TikTok app - owner posts |
| LinkedIn | Share on LinkedIn (`w_member_social`), personal profile | Buffer or Metricool | LinkedIn app |
| X | Pay-per-use API ($0.015-0.20 per post) - needs owner approval | Manual | X app |

**Monitoring and replaceability**
- Token expiry alarms: Google refresh token (7-day death in Testing status), Meta and LinkedIn tokens ([T] about 60 days).
- Quota read-back: `content_publishing_limit`, `threads_publishing_limit`, YouTube quota errors (`quotaExceeded`).
- Changelog watch: YouTube revision history, LinkedIn monthly API versions, X pricing announcements, Meta Graph API version sunsets.
- Never auto-fall-back to a different route after an uncertain outcome; the existing `outcome_uncertain` fence is the right behaviour, otherwise duplicate posts result.
- Keep provider specifics behind the interface so a vendor that shuts down or changes price is replaced by configuration.

## Counter-evidence and caveats

- **No full page reads.** All facts are from search summaries; the summariser can misquote. The two highest-impact items to re-check on the live pages are claim 2 (private lock lifted) and claim 9 (X rates).
- **Google's own docs disagree with each other** on the private lock (revision history vs. a Videos resource copy) and on upload cost (Quota Calculator still shows 1,600). The repository's 15 Nov 2026 decision assumes the lock still exists.
- **Meta's docs disagree** on the Instagram cap (50 vs 100 per 24 h).
- **X sources disagree** on whether Basic and Pro still exist. Billing behaviour for media is reported as undocumented by developers.
- **Vendor pricing rows are weak evidence.** Most were written by competing vendors (Blotato, Upload-Post, Zernio, Postfast). Zernio's "unlimited free posts" conflicts with its own older changelog. Small API resellers can change price, lose their platform audit or shut down.
- **Counter-argument to "skip aggregators":** an aggregator is the only compliant way to post publicly to TikTok without passing TikTok's audit, and it removes token-refresh and API-version maintenance. The cost is a third party holding the account tokens and a free-tier cap.
- **Counter-argument to "AI content cannot earn":** YouTube states channels using AI remain eligible; the excluded class is templated, mass-produced or misleading content. Original, materially varied AI-assisted videos are allowed. The risk is concentrated in volume-first strategies.
- **Counter-argument on the audit lock:** even if the lock is lifted, YouTube still audits API clients periodically and can restrict a project; default-private plus human approval remains the safer setting.
- **Unverified enforcement figures:** the "16 channels / 35M subscribers / $10M" numbers come from one blog and a TechTimes piece, not from YouTube.
- **Not researched:** RPM or revenue-per-view figures; no revenue estimate is given here on purpose.

**Gaps (search budget exhausted before these could be checked)**
- TikTok app-review wording on personal or internal-use apps, and whether inbox/draft upload is exempt from the private-only rule.
- LinkedIn Community Management API eligibility for individuals.
- Official TikTok Creator Rewards country list (Ukraine).
- Metricool Free plan network coverage (X and LinkedIn) on the official pricing page.
- Upload-Post, Zernio, Buffer and vidIQ official pricing pages.

## Implications for FactoryOS

1. **Publishing plumbing is not the bottleneck; do not build more of it.** The official routes for the founder's own accounts are free and their limits (100 YouTube uploads/day, 50 Instagram posts/day, 250 Threads posts/day) exceed any sensible volume by one to two orders of magnitude. A seven-network adapter layer has no payback at zero audience and zero revenue.
2. **Settle the YouTube private-lock question with one approved test upload.** If the November 2026 reversal is real, the existing direct publisher can post publicly with no audit, and the note in `DECISIONS.md` (T-552-YT) should be corrected. Keep `private` as the default either way; the human approval gate stays.
3. **Check the Google OAuth app's publishing status now.** If it is "Testing", the refresh token dies every 7 days and autonomous publishing fails silently a week after each consent. Add token age to `health()`.
4. **Add a read-back step after every publish.** Record actual visibility and processing state in the receipt. This is the only reliable detector of private locks, SELF_ONLY forcing and failed processing, and it keeps the "do not fabricate provider receipts" invariant honest.
5. **Order of work, all at $0:** YouTube (done) -> Instagram and Facebook Reels through a Meta app in Standard Access -> Threads. TikTok through Metricool Free (20 posts/month) or by hand. LinkedIn personal posts through Share on LinkedIn only if LinkedIn is where buyers are. Skip X until a post there is worth $0.015-0.20 and the owner approves the spend.
6. **Do not pay for Metricool Advanced ($53-67/month) or Ayrshare ($149/month).** Nothing in the current stage needs a server-side aggregator API. If one is ever needed, the $5-29/month tier is the place to look, after re-checking prices on the vendors' own pages.
7. **Never use the Playwright runner to post or engage on social networks.** It violates the terms of every platform reviewed and puts the only distribution accounts at risk. Use it for reading public pages and the founder's own dashboards at most.
8. **Analytics at $0:** YouTube Analytics API (`yt-analytics.readonly`) on the existing OAuth grant; Instagram, Facebook and Threads insights through the same Meta app; TikTok and cross-network numbers through the already-connected Metricool and vidIQ MCPs. LinkedIn member-post analytics has no open API - export by hand.
9. **Verdict on the "content factory" as a business.** Ad revenue from mass-produced AI video is the path the platforms have explicitly closed: templated AI content is non-monetisable on YouTube, repeated unoriginal content is demonetised on Meta, and TikTok's programme needs original one-minute videos, 10,000 followers and a supported country. Treat social posting as a distribution channel for a product (MyCast, MyBrief), post few and materially different pieces, and measure the chain separately: views -> subscribers -> sign-ups or leads -> revenue -> net profit. Views and subscribers are not income; today the last three numbers are zero, and no publishing architecture changes that.
10. **Label AI content honestly.** Keep `containsSyntheticMedia` on YouTube and set `is_aigc` on TikTok when the content is AI-generated; disclosure does not reduce reach or eligibility according to YouTube, while a missing label on realistic content can get it removed or restricted.

## Sources

No web page was opened in full (WebFetch blocked by the session network policy). The lists below are the pages whose content was returned by WebSearch and used above, plus repository files that were actually read.

**Official pages surfaced by domain-restricted search**
- https://developers.google.com/youtube/data/revision_history
- https://developers.google.com/youtube/data/getting-started
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/docs/videos?hl=en
- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/data/guides/quota_and_compliance_audits
- https://developers.google.com/youtube/terms/developer-policies
- https://developers.google.com/youtube/reporting/guides/authorization
- https://support.google.com/cloud/answer/10311615
- https://support.google.com/youtube/answer/1311392
- https://support.google.com/youtube/answer/14328491
- https://support.google.com/youtube/answer/2801973
- https://support.google.com/youtube/answer/3399767
- https://support.google.com/youtube/answer/7101720
- https://support.google.com/youtube/answer/7300965
- https://support.google.com/youtube/community-guide/271248162
- https://developers.facebook.com/docs/instagram-platform/content-publishing/
- https://developers.facebook.com/documentation/instagram-platform/app-review
- https://developers.facebook.com/docs/graph-api/overview/access-levels
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit.md
- https://developers.facebook.com/documentation/video-api/guides/reels-publishing
- https://developers.facebook.com/docs/graph-api/reference/video/video_insights/
- https://developers.facebook.com/documentation/threads/overview
- https://developers.facebook.com/docs/permissions
- https://developers.facebook.com/blog/post/2024/06/18/the-threads-api-is-finally-here/
- https://creators.facebook.com/blog/combating-unoriginal-content
- https://en-gb.facebook.com/business/help/169845596919485
- https://about.fb.com/news/2025/04/cracking-down-spammy-content-facebook/
- https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/
- https://transparency.meta.com/governance/tracking-impact/labeling-ai-content/
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- https://developers.tiktok.com/docs/en/tiktok-api-scopes
- https://developers.tiktok.com/docs/en/display-api-get-started
- https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content
- https://www.tiktok.com/safety/en/policies-and-engagement/integrity-authenticity
- https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-09
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-10
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- https://docs.x.com/x-api/introduction
- https://docs.x.com/changelog
- https://docs.x.com/developer-guidelines
- https://help.x.com/en/rules-and-policies/x-automation
- https://devcommunity.x.com/t/x-api-pricing-update-owned-reads-now-0-001-other-changes-effective-april-20-2026/263025
- https://devcommunity.x.com/t/announcing-the-x-api-pay-per-use-pricing-pilot/250253
- https://devcommunity.x.com/t/inform-x-api-ppu-expansions-update/279110
- https://devcommunity.x.com/t/undocumented-postcreate-usage-for-media-uploads-please-clarify-pay-per-use-billing/274646
- https://devcommunity.x.com/t/pay-per-use-billing-issue-overcharged-20x-per-post/263811
- https://help.metricool.com/plans-add-ons-and-api-access-explained-xux1u
- https://help.metricool.com/mcp-limits-and-plan-requirements-h72jg
- https://help.metricool.com/faqs-about-the-metricool-mcp-1i3w0
- https://docs.postiz.com/providers/tiktok
- https://github.com/gitroomhq/postiz-app/issues/1362
- https://postiz.com/
- https://vidiq.com/mcp/

**Secondary and vendor pages surfaced by search**
- https://www.tubefilter.com/2026/07/13/youtube-inauthentic-content-monetization-policy-update/
- https://www.androidheadlines.com/2026/07/youtube-monetization-rules-ai-slop-inauthentic-content.html
- https://deadline.com/2025/12/youtube-fake-movie-trailers-celebrate-hollywood-studios-1236653577/
- https://www.thewrap.com/industry-news/tech/youtube-terminates-screen-culture-kh-studio-over-ai-fake-movie-trailers/
- https://www.techtimes.com/articles/320629/20260715/youtube-wiped-35m-subscribers-over-ai-slop-now-its-judging-your-taste.htm
- https://outlierkit.com/blog/youtube-ai-crackdown
- https://outlierkit.com/resources/vidiq-mcp/
- https://repostit.io/youtube-api-daily-limit/
- https://dev.to/aipredictions_dev/youtube-now-counts-uploads-in-their-own-bucket-100-a-day-one-unit-each-29gm
- https://www.upload-post.com/youtube-api/
- https://www.upload-post.com/best-social-media-apis/
- https://www.upload-post.com/ayrshare-pricing/
- https://www.linkstartai.com/en/agents/upload-post
- https://www.blotato.com/blog/ayrshare-pricing
- https://www.blotato.com/research/social-media-agent-pricing
- https://www.blotato.com/research/social-media-automation-rulebook
- https://zernio.com/blog/buffer-api
- https://zernio.com/changelog/simplified-pricing-plans-for-late-api-users
- https://www.postzen.dev/blog/buffer-api
- https://lokeshkapoor.com/blog/zernio-review
- https://postproxy.dev/blog/x-api-pricing-2026/
- https://postproxy.dev/blog/instagram-reels-api-publishing-guide/
- https://adaptlypost.com/blog/why-does-my-app-need-approval-post-tiktok
- https://nango.dev/docs/api-integrations/youtube/how-to-register-your-own-youtube-api-oauth-app
- https://community.n8n.io/t/youtube-refresh-token-expired/5319
- https://nealschaffer.com/tiktok-creator-rewards-program/
- https://creatorsagency.co/blog/tiktok-creator-rewards-program-2026
- https://monetizedyet.com/facebook-monetization-requirements/
- https://contentmonetizing.com/en/youtube-monetization-countries/
- https://dipak7.com.np/youtube-partner-program-countries-list/
- https://conductatlas.com/platform/linkedin/linkedin-user-agreement/provision/CA-P-023526/prohibition-on-bots-or-inauthentic-automated-engagement/
- https://conductatlas.com/platform/tiktok/tiktok-terms-of-service/prohibition-on-scraping-and-data-extraction/
- https://instantdm.com/blog/is-tiktok-automation-allowed
- https://www.jurist.org/news/wp-content/uploads/sites/4/2021/12/Meta-Platforms-Inc.-v.-Social-Data-Trading-Ltd.pdf

**Repository files read (17 Nov 2026)**
- `/home/user/blackboxlab-factoryos/docs/research/metricool_api.md` (T-520 audit, 1 Nov 2026)
- `/home/user/blackboxlab-factoryos/youtube_publisher.py` (header)
- `/home/user/blackboxlab-factoryos/DECISIONS.md` (T-552-YT entry, 15 Nov 2026)
- `/home/user/blackboxlab-factoryos/.autopilot/answers.md` (Metricool and publishing lines)
