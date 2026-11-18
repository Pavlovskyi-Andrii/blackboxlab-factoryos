# Governed AI access to messengers, e-mail, CRM, inbound leads and customer support (state on 2026-11-17)

## Key claims

> **Method limits - read first.** In this session WebFetch was blocked for every host tried (the egress gateway answered 403 to CONNECT for core.telegram.org, developers.facebook.com, www.whatsapp.com, support.google.com, developers.google.com, developers.hubspot.com, fin.ai), so **no page could be opened in full**. The shared web-search budget of the workflow (200 calls) also ran out after five search batches. Every fact below therefore comes from a WebSearch result extract dated 2026-11-17.
> The search tool returns one merged summary per query. For third-party facts, the URLs next to a fact are the result set the summary was built from; the exact page inside that set could not always be identified.
> Confidence labels are used as follows: `verified_primary` = the text was returned from the official page itself by a search restricted to the official domain (an extract, not a full read); `reported_secondary` = third-party blogs or press; `vendor_claim` = the vendor's own marketing statement; `inference` = my reasoning. Items I could not search at all are marked **[not verified in this session]** and are listed under Gaps.

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | Telegram bots cannot start a conversation: a user must message the bot or add it to a group first. Free limits: about 30 messages per second for bulk sends and 20 messages per minute in one group; above that the API returns 429. Paid broadcasts raise the ceiling to 1,000 messages per second at 0.1 Stars per message above the free 30 per second. | https://core.telegram.org/bots ; https://core.telegram.org/bots/faq ; https://core.telegram.org/bots/api | search extract 2026-11-17 | verified_primary |
| 2 | Since the 8 May 2026 Bot API changelog entry, a bot connected to a Telegram Business account can manage the owner's chats without a Telegram Premium subscription; the reply right covers only private chats with an incoming message in the last 24 hours. Latest Bot API in the results: 10.4, dated 9 November 2026. | https://core.telegram.org/bots/api-changelog ; https://core.telegram.org/api/bots/connected-business-bots ; https://core.telegram.org/constructor/businessBotRights | Bot API 10.4, 2026-11-09 | verified_primary |
| 3 | Automating a personal Telegram account (userbot) is a ban risk by Telegram's own text: flooding or spamming through the API means "banned forever", and all accounts that log in through unofficial API clients are put under automatic observation. | https://core.telegram.org/api/obtaining_api_id | search extract 2026-11-17 | verified_primary |
| 4 | WhatsApp Business Platform: from 1 October 2026 Meta bills every service (free-form) message per message; each business phone number keeps a free tier of 1,000 delivered service messages per month (no rollover). Utility messages sent inside an open 24-hour window are also billed from that date. Without a payment method on file, messages beyond the free tier are simply not delivered. | https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages ; https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing | effective 2026-10-01 | verified_primary |
| 5 | Meta's per-message rates (third-party rate tables, not Meta's rate card): US marketing about $0.025, utility / authentication / service about $0.0034; marketing ranges from about $0.011 (Turkey, India) to about $0.16 (Netherlands). The rate for Ukraine's region was not obtained. | https://www.flowcall.co/blog/whatsapp-business-api-pricing ; https://blueticks.co/blog/whatsapp-business-api-pricing-2026 | blogs dated 2026 (one "Oct 2026") | reported_secondary |
| 6 | WhatsApp Business Solution Terms bar "AI Providers" from offering a general-purpose AI assistant as the primary functionality (effective 15 January 2026; Meta decides at its sole discretion). Task-specific business bots (support, booking, order tracking, lead qualification) remain allowed. On 9 June 2026 the European Commission ordered Meta, as an interim measure, to restore free access for rival AI assistants in the EEA. | https://respond.io/blog/whatsapp-general-purpose-chatbots-ban ; https://dig.watch/updates/meta-changes-whatsapp-terms-to-block-third-party-ai-assistants ; https://ec.europa.eu/commission/presscorner/api/files/document/print/en/ip_26_1276/IP_26_1276_EN.pdf | terms effective 2026-01-15; EC order 2026-06-09 | reported_secondary |
| 7 | Messenger and Instagram messaging: a business may message a person only within 24 hours of that person's message (standard messaging window). The Human Agent tag extends this to 7 days, requires app review, and may not be used for automated messages. | https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy ; https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages | search extract 2026-11-17 | verified_primary |
| 8 | Gmail API: `gmail.send` is a sensitive scope (no third-party security assessment); `gmail.readonly` and `gmail.modify` are restricted scopes and need an annual CASA security assessment when restricted data is stored or transmitted on servers. Unverified apps are capped at 100 new users; apps internal to one Google Workspace organisation need no Google review. | https://developers.google.com/workspace/gmail/api/auth/scopes ; https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification ; https://support.google.com/cloud/answer/13463817 | search extract 2026-11-17 | verified_primary |
| 9 | Gmail sending limits: 500 messages per day for a personal account, 2,000 per day per Google Workspace user (500 on trial), 3,000 unique recipients per day. Bulk-sender rules start near 5,000 messages per day to personal Gmail addresses: SPF, DKIM and DMARC, one-click unsubscribe, spam rate below 0.1 % and never 0.3 % or more. Outlook applies the same 5,000 per day threshold since 5 May 2025. | https://support.google.com/a/answer/166852 ; https://support.google.com/mail/answer/14229414 ; https://support.google.com/a/answer/81126 ; https://techcommunity.microsoft.com/blog/outlook/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730 | search extract 2026-11-17 | verified_primary (Google); reported_secondary (Microsoft, Yahoo) |
| 10 | Free transactional e-mail tiers: Resend 3,000 per month capped at 100 per day (Pro $20 per month for 50,000); Brevo 300 per day; Postmark 100 per month (Basic $15 for 10,000). Amazon SES removed its own free tier for new customers on 21 July 2026 ($0.10 per 1,000 a la carte; new accounts start on the Essentials plan at $0.16 per 1,000). | https://resend.com/pricing ; https://www.brevo.com/features/email-api/ ; https://postmarkapp.com/pricing ; https://aws.amazon.com/blogs/messaging-and-targeting/introducing-amazon-simple-email-service-ses-pricing-plans/ ; https://aws.amazon.com/ses/pricing/ | search extract 2026-11-17; SES change 2026-07-21 | verified_primary |
| 11 | HubSpot free CRM: up to 2 users and 1,000 contacts (accounts created after September 2024), no expiry. A private app on Free or Starter gets 100 requests per 10 seconds and 250,000 calls per day per account. Paid: Starter $20 per seat per month list price (a $7 promotional price is shown for new customers), Sales Hub Professional $90 to $100 per seat per month, Customer Platform Professional $1,300 per month with 6 seats. | https://www.hubspot.com/products/crm ; https://legal.hubspot.com/hubspot-product-and-services-catalog/technical-limits ; https://developers.hubspot.com/docs/api/usage-details ; https://hubspot.com/pricing/sales ; https://www.hubspot.com/pricing/suite | search extract 2026-11-17 | verified_primary |
| 12 | CRM alternatives: Twenty is free to self-host (AGPLv3; cloud about $9 per user per month on annual billing); Attio has a free plan for up to 3 seats (paid $35 and $79 per seat after a reported July 2026 increase); Pipedrive has no free plan (from $14 per seat per month, annual). | https://www.taskrhino.ca/twenty-crm-implementation/twenty-crm-review/ ; https://marketbetter.ai/blog/attio-crm-pricing-breakdown-2026/ ; https://fluidcrm.io/blog/attio-vs-pipedrive/ | third-party reviews, 2026 | reported_secondary |
| 13 | Cold-outreach tooling is not zero-spend: Smartlead from $39 per month, Instantly $37 to $47, Apollo about $49 to $99 per user, Clay from about $167 to $185; one comparison puts a realistic stack at $200 to $350 per month. LinkedIn's User Agreement (section 8.2) prohibits bots and automated messaging; in March 2026 LinkedIn reportedly removed the automation vendor HeyReach from the platform. German law (UWG §7) is described as opt-in even for B2B e-mail. | https://litemail.ai/blog/cold-email-tool-pricing-comparison-2026 ; https://www.lemlist.com/blog/instantly-vs-smartlead ; https://noobclaw.com/blog/linkedin-automation-rules-2026/ ; https://www.lemlist.com/blog/gdpr-cold-email | third-party, 2026 | reported_secondary |
| 14 | AI support agents are priced per outcome: Fin (formerly Intercom) $0.99 per resolution, with a reported 50-outcome ($49) monthly minimum on a non-Intercom help desk; Zendesk about $1.50 (committed) to $2.00 (pay as you go) per automated resolution. Chatwoot Community Edition is free to self-host (MIT) and the cloud "Hacker" plan is free for up to 2 agents; Crisp has a free tier with 2 seats. | https://www.getmacha.com/blog/intercom-fin-pricing ; https://www.eesel.ai/blog/a-complete-guide-to-zendesk-ai-agents-setup-costs-and-best-practices ; https://www.eesel.ai/blog/chatwoot-pricing ; https://www.dragapp.com/blog/crisp-pricing/ | third-party, Aug-Nov 2026 | reported_secondary |
| 15 | OLX Partner API access is moderated: a developer account and an application are required, OLX verifies the application and may refuse the API key; a Ukrainian-language Partner API agreement (valid from 2020-03-31) is listed. Its fee and permitted-use clauses were not obtained. | https://developer.olxgroup.com/terms-and-conditions ; https://developer.olxgroup.com/faq | agreement dated 2020-03-31; extract 2026-11-17 | verified_primary |

## Detailed findings

### 1. Telegram: Bot API, Business bots, Mini Apps and Stars, userbot risk

#### Takeaway
Telegram is the only channel in scope that is free at any realistic FactoryOS volume, has an official bot interface with no review process, and is consent-based by design (the user must write first). The compliant way to let an AI answer in the owner's personal chats is a connected Business bot, not a userbot.

#### Cited findings
- "Bots can't start conversations with users. A user must either add them to a group or send them a message first." Users reach a bot by username search or a `t.me/<bot_username>` link; `/start` with a deep-link parameter begins the interaction. - https://core.telegram.org/bots ; https://core.telegram.org/bots/features ; https://core.telegram.org/api/links
- A bot cannot send more than 20 messages per minute in one group. - https://core.telegram.org/bots/faq
- Bulk notifications: about 30 messages per second by default ("all bots can broadcast up to 30 messages per second to their users by default"); above that the API answers 429. The FAQ suggests spreading notifications over 8 to 12 hours. - https://core.telegram.org/bots/api ; https://core.telegram.org/bots/faq
- The limit applies to proactive bulk sends; replying to incoming user messages at high rates is described as unproblematic in the grammY flood-limit guide (third-party library documentation). - https://grammy.dev/advanced/flood
- Paid broadcasts: enabled in @BotFather, up to 1,000 messages per second; each message above the free 30 per second costs 0.1 Telegram Stars from the bot's balance; only successfully broadcast messages are charged. API parameter: `allow_paid_broadcast`. - https://core.telegram.org/bots/faq ; https://core.telegram.org/bots/api
- **Conflict inside the official documentation:** the FAQ says a bot needs at least 100,000 Stars on its balance and at least 100,000 monthly active users to enable paid broadcasts; the Bot API page says at least 10,000 Stars. The search engine dated the FAQ page as much older than the API page, so the API figure may be the newer one. - https://core.telegram.org/bots/faq ; https://core.telegram.org/bots/api
- Bot API releases returned by the official changelog: 3 April 2026 (managed bots: `can_manage_bots`, managed-bot token methods); 8 May 2026 (Business bots can manage user accounts without Telegram Premium; bot-to-bot messaging; guest mode); 11 June 2026, Bot API 10.1 (Rich Messages); 14 July 2026, Bot API 10.2 (Ephemeral Messages); 9 November 2026, Bot API 10.4 (Widget class, `sendWidget`, `sendSharedWidget`, ephemeral-message reply options, bank-card entity type). - https://core.telegram.org/bots/api-changelog
- Connected business bots: "connecting a business bot does not require Telegram Premium"; the account owner chooses which chats the bot can access; rights are granular (reply, mark as read, delete messages, edit profile, manage stories); the reply right covers private chats that had incoming messages in the last 24 hours. - https://core.telegram.org/api/bots/connected-business-bots ; https://core.telegram.org/api/business ; https://core.telegram.org/constructor/businessBotRights
- Guest mode: a bot can be queried by username from a non-secret private chat, group or supergroup it is not a member of and post its result there; it gets no access to chat history or the participant list; up to three guest bots per message. - https://core.telegram.org/bots/api-changelog
- Managed bots: a manager bot can create and control other bots on behalf of their owners, including fetching and replacing the managed bot's token. - https://core.telegram.org/bots/api-changelog ; https://core.telegram.org/api/layers
- Digital goods and services must be sold only for Telegram Stars (currency `XTR`); third-party payment providers are not allowed for digital goods. Developers earning Stars can receive rewards equivalent to 0.013 USD per Star. Mini Apps can sell digital goods and subscriptions for Stars. - https://telegram.org/tos/bot-developers ; https://core.telegram.org/bots/webapps ; https://telegram.org/blog/telegram-stars ; https://core.telegram.org/api/stars
- Telegram's own statement that it "takes practically no commission" on Stars and that only taxes and payment-system fees apply is a vendor claim. - https://telegram.org/blog/telegram-stars
- Userbot risk: "using the Telegram API for flooding, spamming, faking subscriber and view counters of channels, you will be banned forever"; "all accounts that log in using unofficial Telegram API clients are automatically put under observation"; a wrongly banned user must write to recover@telegram.org, and automated appeals are detected. - https://core.telegram.org/api/obtaining_api_id
- Accounts can be frozen (read-only) for serious ToS violations; a confirmed spam report can limit an account from contacting strangers temporarily or permanently. - https://core.telegram.org/api/auth ; https://telegram.org/privacy
- Bot Platform Developer Terms: violations "may lead to the immediate and permanent ban" of the bot or Mini App and the developer's account. - https://telegram.org/tos/bot-developers
- python-telegram-bot's built-in rate limiter does not handle `allow_paid_broadcast` automatically (library wiki). - https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits

#### Inferences
- At FactoryOS scale (tens to hundreds of users) the free 30 messages per second is never the constraint; paid broadcasts are irrelevant until a bot has on the order of 100,000 monthly users.
- A connected Business bot gives the product an "AI drafts or answers in the owner's own Telegram inbox" capability inside the terms, with a built-in 24-hour window and owner-selected chats. A userbot (Telethon, Pyrogram and similar) gives slightly more reach and a real risk of losing the owner's account, which is also FactoryOS's control channel. The trade is bad.
- Stars make sense only for digital goods sold inside Telegram. The 0.013 USD per Star payout rate means the developer receives less than the buyer pays (app-store fees sit in between); the exact buyer price was not checked.

#### Gaps
- Stars withdrawal conditions (minimum balance, hold period, payout through Fragment in Toncoin) **[not verified in this session]**. Verify at https://telegram.org/tos/stars and https://core.telegram.org/bots/payments-stars.
- The page "AI features for bots" (https://core.telegram.org/api/bots/ai) appeared in results, but its content was not returned.
- Which threshold for paid broadcasts is current (100,000 Stars and 100,000 MAU, or 10,000 Stars).
- Whether Telegram Stars payouts are practically available to a Ukraine-based individual developer: not researched.

### 2. WhatsApp Business Platform; Instagram and Messenger messaging

#### Takeaway
WhatsApp stopped being a free reply channel on 1 October 2026: only 1,000 service messages per number per month remain free. A task-specific business bot is still allowed; a general-purpose assistant sold as the product is not. Instagram and Messenger allow automation only as a reply within 24 hours of the user's message.

#### Cited findings
- Per-message pricing replaced conversation-based pricing (the conversation model is marked "Deprecated" in Meta's documentation). - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/conversation-based-pricing ; https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Service messages were free from 1 November 2024; utility templates inside an open customer-service window were free from 1 July 2025. "Effective October 1, 2026 - Meta will charge on a per-message basis for all service messages"; utility messages sent in response to users inside the open 24-hour window are billed on the same schedule. - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- Free tier: 1,000 delivered service messages per business phone number per month; billing starts with the 1,001st; unused messages do not roll over; the tier does not cover Meta Business Agent messages; eligible government and non-profit organisations keep service messages free. - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- Service-message rates equal the utility and authentication rates of each market, with no volume tiers; Meta's Brazil example is about 0.68 US cents per delivered message. - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- No payment method: service messages inside the free tier are delivered, messages after it are not. Businesses without a payment method by 30 September 2026 have service messages stop once chargeable. - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- Free entry point: messages sent within 72 hours after a user clicks a Click-to-WhatsApp ad or a Facebook Page call-to-action remain free (Meta Business Agent messages excepted). - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Meta Business Agent (Meta's own AI agent) is billed per token from 1 August 2026 at $2.00 per 1 million tokens; Meta says a message typically uses 20,000 to 25,000 tokens, about 4 to 5 US cents per message. - https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- Developers objected to the end of the free service window on Meta's developer forum (community opinion, anecdotal). - https://developers.facebook.com/community/threads/1328420532772816/
- Rates (third-party tables): US marketing $0.025, utility / authentication / service $0.0034; marketing from $0.0109 (Turkey) and $0.0118 (India) to $0.1365 (Germany) and $0.1597 (Netherlands). One blog gives different US utility ($0.004) and authentication ($0.0135) figures and is an outlier. - https://www.flowcall.co/blog/whatsapp-business-api-pricing ; https://blueticks.co/blog/whatsapp-business-api-pricing-2026 ; https://www.engagelab.com/blog/whatsapp-api-pricing ; https://setsmart.io/blog/whatsapp-business-api-pricing
- Solution providers add their own fee; Twilio was reported at $0.005 per message (inbound or outbound) on top of Meta's rates, plus $0.001 per failed message. This came from the same set of third-party pricing guides; the exact guide could not be re-identified and Twilio's own page was not opened. - https://getkanal.com/blog/whatsapp-business-pricing-guide ; https://www.engagelab.com/blog/whatsapp-api-pricing
- AI policy: the Business Solution Terms define "AI Providers" (providers of large language models, generative AI platforms, general-purpose AI assistants) and bar them from using the Business Solution when such technology is "the primary (rather than incidental or ancillary) functionality being made available for use", "as determined by Meta in its sole discretion". Effective 15 January 2026; applied to new accounts from 15 October 2025. - https://dig.watch/updates/meta-changes-whatsapp-terms-to-block-third-party-ai-assistants ; https://respond.io/blog/whatsapp-general-purpose-chatbots-ban ; https://www.alibabacloud.com/help/en/chatapp/use-cases/whatsapp-ai-policy-2026-guide
- Allowed after the change (per solution-provider guides): lead qualification, appointment booking, customer support, order tracking. OpenAI announced that ChatGPT would leave WhatsApp after 15 January 2026. - https://respond.io/blog/whatsapp-general-purpose-chatbots-ban ; https://gulfnews.com/technology/no-more-chatgpt-and-perplexity-on-whatsapp-meta-bans-major-ai-chatbots-from-2026-1.500316016
- European Commission, 9 June 2026: interim measures ordering Meta to reinstate access for competing general-purpose AI assistants on the pre-October 2025 terms, free of charge, until a final decision; Meta called it "regulatory overreach" and said it would appeal. Whether Meta complied was not found. - https://ec.europa.eu/commission/presscorner/api/files/document/print/en/ip_26_1276/IP_26_1276_EN.pdf ; https://decrypt.co/370580/eu-orders-meta-open-whatsapp-rival-ai-chatbots ; https://www.houthoff.com/insights/news/a-rare-show-offorce-commission-deploys-interim-measures-against-meta-to-safeguard-ai-competition/
- Messenger and Instagram: "When a person sends your Page or Instagram Professional account a message, your app has up to 24 hours to send a message" (standard messaging window); promotional content is allowed inside it. - https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy ; https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Human Agent tag: replies up to 7 days after the person's message, only for issues that cannot be resolved inside the standard window; only for apps that passed app review; automated messages and content unrelated to the inquiry are disallowed uses; misuse of message tags can restrict the Page or Instagram account. - https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
- Private replies to a comment: a single message, within 7 days of the comment. - https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api

#### Inferences
- A WhatsApp number with no payment method attached is a hard zero-spend cap: at most 1,000 free-form replies per month, then silence. That is acceptable for a pilot and unacceptable for a support promise.
- A MyCast or MyBrief delivery or support bot is task-specific, so it is on the allowed side of the AI clause; a "chat with our AI about anything" bot is not. Because Meta decides at its sole discretion, WhatsApp must never be the only delivery channel.
- Meta sells its own AI agent on the same platform where it restricts rivals. This is a standing platform risk for any AI-first business that depends on WhatsApp.
- Any proactive WhatsApp message (outside the 24-hour window) needs an approved template and is billed; in the US table a marketing template costs about 7 times more than a utility message ($0.025 versus $0.0034).

#### Gaps
- Meta's own rate card for Ukraine and for "Rest of Central and Eastern Europe" **[not verified in this session]**: https://business.whatsapp.com/products/platform-pricing.
- Template approval rules, opt-in requirements, messaging-limit tiers and business verification steps **[not verified in this session]**.
- The verbatim text of the AI Providers clause on https://www.whatsapp.com/legal/business-solution-terms (host blocked); the wording above is quoted through secondary sources.
- Instagram messaging app-review requirements and rate limits; any Meta rule on disclosing automated chat **[not verified in this session]**.

### 3. Gmail and Google Workspace; bulk-sender rules; transactional providers

#### Takeaway
For the owner's own mailbox, sending through `gmail.send` needs no security assessment, and the realistic ceiling is a few hundred messages per day. The bulk-sender rules bite only near 5,000 messages per day, but authentication (SPF, DKIM, DMARC) is worth setting from day one. A free transactional provider covers every current FactoryOS need.

#### Cited findings
- Scope classes: `gmail.send` is sensitive ("Send email on your behalf"); `gmail.readonly` and `gmail.modify` are restricted. Google's minimum-scope guidance: `gmail.send` is sufficient to compose and send; use `gmail.metadata` rather than `gmail.readonly` for monitoring. - https://developers.google.com/workspace/gmail/api/auth/scopes ; https://support.google.com/cloud/answer/13807380
- Projects requesting only sensitive scopes do not need a third-party security assessment. Restricted scopes need one when the app stores or transmits restricted data on servers; Google uses the CASA framework (risk-based tiers) and all applications must be revalidated every year. - https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification ; https://support.google.com/cloud/answer/13465431
- Unverified apps that access restricted or sensitive scopes have a 100 new-user cap. - https://support.google.com/cloud/answer/13463817
- Apps used only inside one Google Workspace organisation (user type Internal) need no Google review for sensitive or restricted scopes. - https://developers.google.com/workspace/guides/configure-oauth-consent
- CASA cost estimates conflict and both come from vendors: about $500 per year for the assessor (Unipile) versus $15,000 to $75,000 with annual renewal (Truto, which sells an alternative). No Google or assessor price list was found. - https://www.unipile.com/gmail-api-scopes-guide/ ; https://truto.one/google.md
- Sending limits: Google Workspace 2,000 messages per day per user (mail merge 1,500; trial accounts 500), 10,000 total recipients and 3,000 unique recipients per day, 500 external recipients per message, rolling 24 hours, changeable without notice. Personal Gmail: 500 messages per day over SMTP or IMAP, up to 100 recipients per message. - https://support.google.com/a/answer/166852 ; https://developers.google.com/workspace/gmail/imap/imap-smtp ; https://support.google.com/mail/answer/22839
- Google bulk-sender definition: close to 5,000 messages or more to personal Gmail accounts within 24 hours, pooled across the primary domain and its subdomains. Such senders need SPF, DKIM and DMARC (policy may be `p=none`) and one-click unsubscribe for marketing and subscribed messages. - https://support.google.com/mail/answer/14229414 ; https://support.google.com/a/answer/81126
- Spam rate: keep below 0.1 % and never reach 0.3 % or higher; above 0.3 % a bulk sender is ineligible for mitigation until the rate stays below 0.3 % for seven consecutive days; measured daily in Postmaster Tools. Non-compliant mail faces temporary and permanent rejections; enforcement ramped up from November 2025. - https://support.google.com/mail/answer/14229414 ; https://support.google.com/mail/answer/14668346
- Microsoft (Outlook.com, Hotmail.com, Live.com): since 5 May 2025, domains sending more than 5,000 messages per day must pass SPF and DKIM and publish DMARC of at least `p=none` aligned with the From domain. Sources disagree on whether non-compliant mail is junked or rejected and on whether one-click unsubscribe is mandatory (a functional, visible unsubscribe link is required). - https://techcommunity.microsoft.com/blog/outlook/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730 ; https://redsift.com/tools/microsoft-sender-requirements ; https://mailtrap.io/blog/outlook-new-email-sender-requirements/
- Yahoo: described by secondary guides as mandating RFC 8058 one-click unsubscribe and a complaint rate under 0.3 %, like Google. Yahoo's own page was not reached. - https://redsift.com/tools/microsoft-sender-requirements ; https://mailtrap.io/blog/outlook-new-email-sender-requirements/
- Resend: free plan $0 for 3,000 e-mails per month with a 100 per day cap, 3 domains; Pro $20 per month for 50,000 e-mails with no daily limit, overage $0.90 per 1,000; Scale $90 for 100,000. A Resend docs page lists a different tier (Pro $35 per month for 100,000), so one of the two is stale. - https://resend.com/pricing ; https://resend.com/docs/knowledge-base/account-quotas-and-limits ; https://resend.com/docs/knowledge-base/what-is-resend-pricing
- Postmark: free developer plan of 100 e-mails per month that never expires; Basic $15 per month for 10,000; overage $1.80 per 1,000 in the 10,000 to 125,000 band; no tier between 100 and 10,000. - https://postmarkapp.com/pricing ; https://postmarkapp.com/support/article/1285-pricing-billing-faq
- Amazon SES: as of 21 July 2026 the SES-specific free tier (3,000 message charges per month for 12 months) is no longer available to new customers; existing users keep it to the end of their 12 months. New accounts start on the Essentials plan ($0.16 per 1,000 e-mails up to 10 million per month) and may switch to a la carte pricing at $0.10 per 1,000. AWS Free Tier credits of up to $200 can be applied; the two AWS pages state different windows for the credits (six months versus twelve). - https://aws.amazon.com/blogs/messaging-and-targeting/introducing-amazon-simple-email-service-ses-pricing-plans/ ; https://aws.amazon.com/ses/pricing/
- Brevo: free plan of 300 e-mails per day with API, webhooks and tracking, no time limit, no card; Starter from $9 per month for 5,000 e-mails per month. - https://www.brevo.com/features/email-api/ ; https://www.brevo.com/free-smtp-server/
- Brevo's "99 % deliverability" headline is a vendor claim. - https://www.brevo.com/products/transactional-email/
- Mailgun (third-party comparisons only): free 100 e-mails per day; paid entry $15 per month for 10,000. One comparison calls the free tier a trial only. - https://thetechhacker.com/2026/11/14/best-transactional-email-api/ ; https://www.buildmvpfast.com/api-costs/email

#### Inferences
- For FactoryOS's own use (one owner mailbox, one consent screen) the restricted-scope assessment does not apply in practice: the app stays below 100 users or is Workspace-internal. The assessment becomes a real cost only if FactoryOS is sold as a multi-tenant product that reads customers' mailboxes, which is a reason not to build that feature before revenue.
- Daily caps make the free tiers behave differently: Resend free is fine for transactional mail but cannot send one announcement to more than 100 people in a day; Brevo free allows 300 per day (about 9,000 per month). SES is no longer a free option for a new account.
- At FactoryOS volumes the 5,000 per day threshold is far away, but Gmail's spam-rate logic applies to every sender, and a new domain with a handful of complaints out of a few hundred messages can exceed 0.3 % at once. Low volume does not protect a sender; relevance and consent do.

#### Gaps
- Gmail API quota units (per-user rate and cost of `messages.send`) **[not verified in this session]**: https://developers.google.com/workspace/gmail/api/reference/quota.
- Whether refresh tokens of an OAuth app left in "Testing" status still expire after seven days **[not verified in this session]** (background knowledge; check https://developers.google.com/identity/protocols/oauth2).
- Official Mailgun pricing page and Yahoo Sender Hub page were not reached.

### 4. Cold outreach: law, deliverability, tool costs, LinkedIn

#### Takeaway
An AI-run cold-outbound machine conflicts with all three hard constraints of the project: it costs money (about $200 to $350 per month by third-party estimates), it needs per-country legal judgement, and on LinkedIn it breaks the user agreement. What remains realistic is founder-led, low-volume, individually written B2B e-mail where AI drafts and a human sends.

#### Cited findings
- Tool prices (third-party comparisons, 2026): Smartlead Base $39 per month (2,000 active leads, 6,000 e-mails per month, unlimited mailboxes), Pro about $94; Instantly Growth $47 per month billed monthly or $37 billed annually, Hypergrowth $97; Apollo about $49 to $99 per user per month (one source: Basic $65 billed monthly); Clay from $185 per month ($167 billed yearly), and Clay is an enrichment tool, not a sender. - https://www.lemlist.com/blog/instantly-vs-smartlead ; https://moderninbound.com/blog/clay-vs-smartlead ; https://growth.cx/blog/instantly-vs-apollo-vs-smartlead/ ; https://instantly.ai/blog/best-instantly-alternatives-outbound-sales/
- One comparison estimates a realistic total of $200 to $350 per month once mailboxes, domains and data are included. - https://litemail.ai/blog/cold-email-tool-pricing-comparison-2026
- GDPR and ePrivacy for B2B e-mail differ by country (vendor and consultancy guides, not regulator text): Germany (UWG §7) is treated as opt-in even for B2B; France allows B2B prospecting when the message relates to the recipient's profession, with strict opt-out; the Netherlands has a B2B exemption for corporate addresses with opt-out in every message; in the UK, PECR's opt-in rule covers individual subscribers (including sole traders and partnerships) and not corporate subscribers. Italy, Spain and Poland are placed in "moderate" or "strict" groups depending on the guide. - https://www.lemlist.com/blog/gdpr-cold-email ; https://asphia.consulting/blog/cold-email-gdpr-europe-2026/ ; https://www.quarvio.io/blog/cold-email-gdpr-guide ; https://prospeo.io/s/gdpr-cold-email
- LinkedIn: commentary points to section 8.2 of the User Agreement (no bots or other automated methods to access the services, add or download contacts, send or redirect messages) and to the "Prohibited software and extensions" help page (accounts may be restricted or shut down). One source reports that in March 2026 LinkedIn removed the company page of the automation vendor HeyReach and banned its account; another describes a tiered enforcement ladder without a primary source (anecdotal). - https://noobclaw.com/blog/linkedin-automation-rules-2026/ ; https://www.revenueflow.com/blog/linkedin-web-scraping ; https://www.anybiz.io/blogs/linkedin-automation-what-actually-changed/ ; https://sellinger.ai/blog/linkedin-terms-of-service-and-automation
- The Ninth Circuit's 2022 hiQ ruling held that scraping publicly available data does not by itself violate the Computer Fraud and Abuse Act; the contractual prohibition is a separate basis for enforcement. - https://www.revenueflow.com/blog/linkedin-web-scraping
- Repository fact: a live check on 2026-11-17 showed LinkedIn and OLX answer the FactoryOS EC2 runner with HTTP 403; the project decided to use only the official LinkedIn posting API, to leave LinkedIn messages as drafts the owner sends by hand, and not to build people search. - /home/user/blackboxlab-factoryos/DECISIONS.md (section "2026-11-17 - T-700")

#### Inferences
- Realistic and compliant outbound for this project: at most 10 to 20 individually researched e-mails per working day, sent by the owner from a real mailbox on an authenticated domain, to business addresses in jurisdictions that permit B2B opt-out contact (US, UK corporate subscribers, France and the Netherlands for profession-relevant offers); every message carries the sender's identity, a postal address and a working opt-out; Germany and private (non-corporate) addresses are excluded. AI does the research and the draft; the existing approval gate does the send.
- Cost framing: tooling at $200 to $350 per month must be covered by net profit from outbound-sourced customers. With no validated offer and no paying customer, the expected return cannot be estimated, so the spend is not justified now. A manual pilot costs $0 and tests the same hypothesis (does anyone reply and pay).
- Sending cold e-mail through a transactional provider (Resend, Postmark, SES) risks suspension of the account that also carries product mail, because these providers restrict unsolicited mail in their acceptable-use policies **[policies not verified in this session]**. Keep product mail and any prospecting on separate domains or subdomains.

#### Gaps
- CAN-SPAM requirements and the current per-e-mail penalty **[not verified in this session]**. Background knowledge: opt-out regime that also covers B2B; requires truthful headers and subject, identification as an advertisement, a physical postal address, and honouring opt-outs within 10 business days; the FTC's 2025 inflation-adjusted maximum was $53,088 per e-mail. Verify at https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business.
- Ukrainian law **[not verified in this session]**. Background knowledge: the Law of Ukraine "On Electronic Commerce" (No. 675-VIII, 2015), Article 10, allows commercial electronic messages on the basis of the recipient's consent, or without consent only if the recipient can refuse further messages; the Law "On Electronic Communications" (No. 1089-IX, in force from 2022) restricts unsolicited electronic messages; the GDPR-style draft personal-data law No. 8153 passed first reading in November 2024, and its 2026 status is unknown. Verify at https://zakon.rada.gov.ua/laws/show/675-19 and https://zakon.rada.gov.ua/laws/show/1089-20.
- GDPR applies to a Ukraine-based sender who offers goods or services to people in the EU (Article 3(2)) **[background knowledge, not re-verified]**.
- No regulator text (CNIL, ICO, Dutch AP, German authorities) was opened; the country rules above are second-hand.
- Official pricing pages of Instantly, Smartlead, Apollo and Clay were not reached.

### 5. CRM: HubSpot free and paid, alternatives, lead capture

#### Takeaway
HubSpot Free is enough as a system of record for the first 1,000 contacts and its API limits are far above FactoryOS needs. The cliff is price: the next meaningful tier is tens to hundreds of dollars per seat. A leads table in FactoryOS's own database, mirrored to HubSpot Free or Notion, keeps the CRM replaceable.

#### Cited findings
- "With up to two users, 1,000 contacts, and no limits on customer data, HubSpot's free CRM functionality is 100% free, with no expiration date." - https://www.hubspot.com/products/crm
- Contact cap in the Products and Services Catalog: 1,000 for free accounts, 15 million for paid accounts. Accounts created before September 2024 kept the old 1,000,000 limit; a HubSpot community moderator states there is no workaround on Free above 1,000 contacts. - https://legal.hubspot.com/hubspot-product-and-services-catalog/technical-limits ; https://community.hubspot.com/t5/Account-Settings/Contact-Limit-1000/td-p/1274101
- Other free-tier limits reported by third parties: 1 deal pipeline, 10 custom properties, HubSpot branding on forms, e-mails and meeting links; companies and deals share a separate 1,000-record cap. The monthly marketing e-mail allowance is reported inconsistently (about 2,000 versus 300). - https://smbdashboard.com/blog/hubspot-free-crm-limitations ; https://scalry.com/blogs/hubspot-free-crm-limits
- API limits for private apps: Free and Starter 100 requests per 10 seconds per app and 250,000 per day per account; Professional 190 per 10 seconds and 625,000 per day; Enterprise 190 per 10 seconds and 1,000,000 per day. The burst limit is per app; response headers such as `X-HubSpot-RateLimit-Remaining` report the remaining budget; up to 20 legacy private apps per account. - https://developers.hubspot.com/docs/api/usage-details ; https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview
- The API limit-increase add-on figures conflict across HubSpot's own pages (250 versus 200 per 10 seconds; the product catalog lists 350 with one capacity pack). - https://developers.hubspot.com/docs/api/usage-details ; https://legal.hubspot.com/hubspot-product-and-services-catalog/technical-limits
- CRM Search API: a separate limit of 5 requests per second per account (third-party). - https://www.scopiousdigital.com/blog/hubspot-api-rate-limits-production
- Prices on HubSpot's pages: Sales Hub free for up to 2 users; Starter "normally priced at $20/month per seat", with a limited-time price of $7 per seat per month on annual billing for new customers; Sales Hub Professional $90 per seat per month annual or $100 monthly; Customer Platform Professional $1,300 per month including 6 seats, additional core seats from $45 per month. Starter allows 50 restricted workflows, Professional up to 300. - https://hubspot.com/pricing/sales ; https://www.hubspot.com/pricing/suite ; https://www.hubspot.com/products/crm/starter
- Repository fact: HubSpot disabled creation of legacy public apps in 2026; own server-to-server tasks can use Service Keys; OAuth access tokens last 1,800 seconds. - /home/user/blackboxlab-factoryos/docs/research/oauth_providers.md
- Twenty: open-source core under AGPLv3, free to self-host with unlimited users and records; the operator carries server, upgrade and backup costs (one estimate: $500 to $1,000 per year in hosting). Cloud Pro about $9 per user per month billed yearly ($12 monthly); Organization $19 in most sources (one says $39). Sources disagree on whether SSO and row-level permissions need a paid key when self-hosted. - https://www.taskrhino.ca/twenty-crm-implementation/twenty-crm-review/ ; https://stackbinary.io/insights/twenty-crm-vs-attio-vs-hubspot ; https://makerstack.co/reviews/twenty-crm-review/ ; https://opsily.com/hosting/twenty-crm/twenty-crm-cost
- Attio: free plan for up to 3 seats; Plus $35 and Pro $79 per seat per month on annual billing ($44 and $99 monthly) after a price rise reported for July 2026; many sites still quote $29 and $69; AI and enrichment are metered in credits. - https://marketbetter.ai/blog/attio-crm-pricing-breakdown-2026/ ; https://coworker.ai/blog/attio-pricing
- Pipedrive: no free plan, 14-day trial; per seat per month on annual billing: Lite $14, Growth $39, Premium $59, Ultimate $79; add-ons priced separately. - https://fluidcrm.io/blog/attio-vs-pipedrive/ ; https://www.folk.app/articles/pipedrive-vs-attio

#### Inferences
- At zero customers a CRM is a list, not a platform. The cheapest correct design is: the lead record lives in FactoryOS's own store (already the pattern for consented feedback and the held mail outbox), and an optional one-way mirror goes to HubSpot Free through a private-app token or service key. If HubSpot changes its free tier again (it cut the contact cap from 1,000,000 to 1,000 in September 2024), nothing is lost.
- Twenty self-hosted is free in licence terms but adds a second database-backed service to operate on the existing EC2 host. Before the first paying customer that is cost without return.
- The multi-tenant HubSpot OAuth slot already present in the roadmap serves future customers' portals, not the founder's own lead tracking. It should not be on the critical path to first revenue.

#### Gaps
- HubSpot free forms, the Forms submission API and webhook availability by tier **[not verified in this session]**. Background knowledge: free forms exist; private apps can subscribe to CRM webhooks; a workflow "send webhook" action needs a Professional-level hub.
- Notion as a CRM: API rate limit (about 3 requests per second per integration) and free-plan limits **[not verified in this session]**: https://developers.notion.com/reference/request-limits.
- Official pricing pages of Twenty, Attio and Pipedrive were not reached.

### 6. Customer support: Chatwoot, Fin, Zendesk AI, Crisp, Plain

#### Takeaway
Per-resolution AI pricing ($0.99 to $2.00) is designed for companies with existing ticket volume. A solo founder with no customers needs a monitored address and one chat entry point first; a shared inbox product comes later, and Chatwoot or Crisp can cover it at $0.

#### Cited findings
- Fin: $0.99 per outcome, billed once per conversation; an outcome is a confirmed resolution or an assumed one (the customer stops asking for 24 hours after Fin's last answer). Reported: $1.99 per voice outcome; $9.99 per qualified sales lead; on a non-Intercom help desk a 50-outcome monthly minimum costing $49; Intercom help-desk seats about $29 to $132 per seat per month on annual billing. - https://www.getmacha.com/blog/intercom-fin-pricing ; https://www.getmacha.com/blog/intercom-fin-ai-agent-complete-guide ; https://corebee.ai/blog/intercom-fin-pricing-real-math-2026
- Blogs report that Salesforce agreed on 15 June 2026 to acquire Fin (the company formerly called Intercom) for about $3.6 billion and closed on 10 September 2026, with the $0.99 rate unchanged. Not confirmed from a primary source in this session. - https://www.getmacha.com/blog/intercom-fin-pricing ; https://aissist.io/insights/intercom-fin-review
- Zendesk: about $1.50 per automated resolution on a committed plan and $2.00 pay as you go; plans include a few resolutions (5 per agent per month, 10 on Suite Professional); no free plan, 14-day trial. Sources disagree on whether Zendesk publishes the rate. - https://www.eesel.ai/blog/a-complete-guide-to-zendesk-ai-agents-setup-costs-and-best-practices ; https://markaicode.com/pricing/zendesk-pricing/ ; https://corepiper.com/blog/zendesk-ai-agent-pricing-2026/
- Chatwoot: Community Edition free to self-host, MIT-licensed (the `enterprise/` directory is licensed separately), without Captain AI, voice or SSO. Cloud per agent per month on annual billing: Hacker $0 for up to 2 agents, Startups $19, Business $39, Enterprise $99; Captain AI credits 300, 500 and 800 per month, extra $20 per 1,000. Sources disagree on which self-hosted paid tier unlocks Captain. - https://www.eesel.ai/blog/chatwoot-pricing ; https://selfhostoffice.com/pricing/chatwoot/ ; https://achiya-automation.com/en/blog/chatwoot-pricing/
- Crisp: permanent free tier with 2 seats and no AI credits; Mini $45, Essentials $95, Plus $295 per month per workspace (not per seat); the AI agent draws from a separate credit pool. One source saw no free plan on the pricing page on 26 October 2026. - https://www.dragapp.com/blog/crisp-pricing/ ; https://www.featurebase.app/blog/crisp-pricing ; https://www.eesel.ai/blog/crisp-pricing
- Plain: no free plan, 7-day trial; Foundation $35 or $45 per seat per month depending on the source; Horizon $99 per user or $299 per month base depending on the source; AI metered in credits from 13 July 2026. - https://www.featurebase.app/blog/plain-pricing ; https://unthread.io/blog/plain-pricing/ ; https://www.getmacha.com/blog/plain-complete-guide

#### Inferences
- Cost illustration (assumption: every conversation is resolved by the AI agent): 100 resolutions per month cost $99 on Fin and $150 to $200 on Zendesk, before seats. With no paying customers these are costs against zero revenue.
- FactoryOS already has an LLM path inside existing subscriptions and an approval gate. Drafting support replies with it and sending after human approval costs $0 and matches the "controllable" requirement better than an external autonomous agent.
- Order of need for a solo founder: (1) one support address plus the Telegram bot, with a response-time promise the founder can keep; (2) a public FAQ or help page that the bot and the drafts cite; (3) only when volume exceeds what one inbox handles, a shared inbox (Chatwoot cloud free plan or Crisp free); (4) per-resolution AI only when the saved human time is worth more than the fee.

#### Gaps
- API access terms of Chatwoot, Crisp, Plain, Fin and Zendesk (rate limits, which plan includes API and webhooks) **[not verified in this session]**.
- Official pricing pages (fin.ai/pricing, chatwoot.com/pricing, crisp.chat, plain.com, zendesk.com) were not reached; all figures above are third-party.
- Resource needs of self-hosted Chatwoot (PostgreSQL, Redis, background workers) on the existing EC2 host were not measured.

### 7. Marketplaces and classifieds: OLX Partner API

#### Takeaway
The official Partner API is the only legitimate route to OLX, access is granted case by case, and its terms could not be read. Scraping or browser automation is both blocked in practice and against the project's own rules.

#### Cited findings
- "In order to use OLX Group Partner APIs and services, you will need to accept ... the applicable terms and conditions"; country versions are listed, including a Ukrainian-language OLX Partner API agreement valid from 2020-03-31. - https://developer.olxgroup.com/terms-and-conditions ; https://developer.olxgroup.com/docs/terms-conditions
- Process in the Developer Center terms: set up a developer account in the Application Manager, register an application, OLX verifies it, and "after positive validation, the Developer obtains the OLX Group API Key"; OLX "reserves the right to verify any Application ... and to refuse to provide the OLX Group API Key". Support contact: developer-support@olx.com. - https://developer.olxgroup.com/terms-and-conditions ; https://developer.olxgroup.com/faq
- A third-party integration guide describes the Ukrainian portal: open https://developer.olx.ua and create an app with "Add App"; another source says registration is moderated by OLX. The API uses OAuth. - https://garazd.biz/en/blog/odoo-integration/odoo-olx-integration ; https://developer.olx.pl/swagger/20
- Paid third-party scrapers for OLX Ukraine exist on Apify. They are not an official interface. - https://apify.com/studio-amba/olx-ua-scraper.md
- Repository fact: OLX answers the FactoryOS EC2 runner with HTTP 403 (CloudFront); task T-701 is planned on the Partner API and waits for the owner's partner registration. - /home/user/blackboxlab-factoryos/ROADMAP.md (T-701) ; /home/user/blackboxlab-factoryos/DECISIONS.md

#### Inferences
- The Partner API is built for integrators that manage adverts for OLX sellers (the Odoo connector above is a typical client). It is a distribution channel only if FactoryOS has something to list or a seller-tool product; neither exists today.
- Approval is outside the founder's control and its duration is unknown, so OLX cannot sit on the path to first revenue.

#### Gaps
- Text of the Ukrainian Partner API agreement: permitted use, fees, rate limits, rules on messaging buyers, and whether an individual (not a company) can register **[not obtained]**.
- Endpoint coverage for Ukraine (adverts, threads and messages, payments) **[not verified in this session]**.
- Other marketplaces relevant in Ukraine (Prom.ua, Rozetka seller API) were not researched: the search budget ran out.

### 8. Recommended minimal, replaceable channel stack under zero additional spend

#### Takeaway
Inbound first, on two channels: a Telegram bot and e-mail on the product's own domain. Everything else is deferred until a paying customer asks for it. Every outbound message to a person who has not written first stays behind the human approval gate.

#### Cited findings
- All figures used below are cited in sections 1 to 7; this section adds no new facts.

#### Inferences - the stack

| Layer | Now (0 customers), cost $0 | Fallback | First paid step and trigger |
|---|---|---|---|
| Conversational channel | Telegram bot through the Bot API; lead capture through `t.me/<bot>?start=<source>` deep links | E-mail | None foreseeable (paid broadcasts start to matter near 100,000 monthly users) |
| Owner's personal Telegram | Connected Business bot with reply right only, in owner-selected chats; no userbot | Owner replies by hand | None |
| Product and transactional e-mail | Resend free (3,000 per month, 100 per day) on an authenticated domain; already the repository default | Brevo free (300 per day) behind the same sender interface | Resend Pro $20 per month when the 100 per day cap blocks real mail |
| 1:1 business e-mail | Owner's Gmail; AI drafts, owner sends; `gmail.send` only if automated | Plain SMTP with an app password | Google Workspace seat only if a custom-domain mailbox is needed |
| Lead store | Own FactoryOS table with source, consent, timestamps | Notion database mirror | None |
| CRM | Optional one-way mirror to HubSpot Free (1,000 contacts, 2 users) | Attio free (3 seats) or Twenty self-hosted | HubSpot Starter (about $20 per seat per month list) only when a second salesperson exists |
| Support | Support address plus Telegram bot plus a public FAQ; LLM drafts, human approves | Chatwoot cloud free plan or Crisp free | Per-resolution AI only with measured ticket volume |
| WhatsApp | Not connected | - | Connect when a paying customer segment requires it; keep no payment method on file to hold the 1,000 free messages per month as a hard cap |
| Instagram and Messenger DMs | Owner answers by hand in the app | - | API only after app review and real DM volume |
| Cold outbound | Manual, founder-led, at most 10 to 20 messages per day, approved one by one | - | Paid sequencer only after a manual pilot produced paying customers |
| LinkedIn | Official posting API (built, T-700); messages by hand | - | None; automation tools are against the user agreement |
| OLX | Wait for Partner API approval (T-701) | - | None |

#### Inferences - monitoring and controls
- E-mail: SPF, DKIM and DMARC on the sending domain; DMARC aggregate reports to a mailbox; Google Postmaster Tools (free) for the daily spam rate with an alert at 0.1 %; bounce and complaint webhooks from the provider written to the outbox record; a `List-Unsubscribe` one-click header on every non-transactional message even below bulk thresholds.
- Telegram: count 429 responses and honour `retry_after`; one queue per chat; never retry a send blindly.
- HubSpot: read `X-HubSpot-RateLimit-Remaining`; the mirror is idempotent and can be switched off without data loss.
- WhatsApp (if ever connected): count service messages per number against the 1,000 free tier and alert at 80 %.
- Governance: one provider-neutral outbox with an idempotency key per message, a per-channel kill switch (the repository already uses this pattern for quiz mail), a consent record per contact and channel, and a log of who approved each outbound message.

#### Gaps
- No delivery or reply-rate data exists for FactoryOS itself, so no channel can be ranked by return. The first measurement to collect is the conversion from content views to bot starts or e-mail sign-ups (leads), and from leads to a first payment.

## Counter-evidence and caveats

- **No page was read in full.** WebFetch was blocked by the session's network policy and the search budget ended early. Treat every number as "needs a click before money is committed". The hosts that would have to be allowed are listed under Sources.
- **Conflicts inside official sources.** Paid-broadcast eligibility on Telegram (100,000 Stars and 100,000 MAU in the FAQ versus 10,000 Stars on the API page). HubSpot's API add-on limits (three different figures). Resend Pro ($20 for 50,000 on the pricing page versus $35 for 100,000 in a docs article). The window for AWS Free Tier credits (six versus twelve months).
- **Conflicts between secondary sources.** Attio ($29 and $69 versus $35 and $79), Twenty Organization ($19 versus $39), Plain Foundation ($35 versus $45), Crisp's free plan (one source could not see it on 26 October 2026), the self-hosted Chatwoot tier that includes Captain, Mailgun's free tier (permanent versus trial), and Microsoft's handling of non-compliant bulk mail (junk versus reject).
- **Dating of the WhatsApp change.** Meta's page is written partly in the future tense ("will charge"); because today is after 1 October 2026 I treat the change as in force, but I did not see a post-October rate card.
- **Events after my training cutoff** (June 2026) rest only on search extracts: Bot API 10.4, the SES free-tier removal on 21 July 2026, the Salesforce acquisition of Fin, the Attio price rise, the European Commission's interim measures. The Fin acquisition in particular is reported only by blogs.
- **Against "skip WhatsApp".** In many markets WhatsApp is the default business channel and 1,000 free replies per month are enough for a pilot. If the first paying segment is outside Ukraine (EU, Latin America, India), WhatsApp may be the right first channel and Telegram the wrong one. The recommendation above assumes a Ukraine-first or Telegram-native audience, which is an assumption, not a measured fact.
- **Against "no cold outbound".** The project has content and products but no revenue; views and subscribers have not turned into paying customers. Waiting for inbound may simply be slow. A small manual outbound test is the cheapest way to learn whether anyone pays, and refusing all outbound would be a mistake in the other direction.
- **Against "HubSpot Free is safe".** HubSpot cut the free contact cap by a factor of 1,000 in September 2024. A free tier is a marketing budget of the vendor and can change again.
- **Against "self-hosting is free".** Twenty and Chatwoot cost no licence fee, but they add services, memory use, upgrades and security patching on a host that already runs the worker. The founder's time is the binding constraint.
- **Legal notes are not legal advice.** The country rules for B2B e-mail come from vendor blogs with a commercial interest in cold e-mail being legal. Ukrainian law and CAN-SPAM were not re-checked. Before any outbound to EU recipients, read the regulator's own guidance for that country.
- **Telegram is also a single point of failure.** It is the control channel, the delivery channel and the proposed lead channel. An account or bot ban, or a regional block, removes all three at once; e-mail must work independently.

## Implications for FactoryOS

1. **Verdict.** The channel problem is solved at $0 for the stage the company is at. Telegram bot plus authenticated e-mail plus an own lead table is sufficient to take the first 100 leads and the first 10 customers. Channel infrastructure is not what stands between FactoryOS and revenue; the missing piece is an offer someone pays for.
2. **Do not build an autonomous outbound agent.** It breaks zero-spend ($200 to $350 per month for tooling by third-party estimates), needs country-by-country legal judgement, is prohibited on LinkedIn, and puts the sending domain and the owner's accounts at risk. Keep "AI researches and drafts, the owner approves and sends", with a hard daily cap. This is also the only form consistent with the repository's approval gate.
3. **Never automate a personal account.** No Telegram userbot, no LinkedIn browser automation, no OLX scraping. Telegram's connected Business bot (free since May 2026) is the sanctioned substitute for an AI in the owner's inbox.
4. **Keep WhatsApp, Viber and Instagram DMs as "planned".** The repository already shows them as disabled; that is correct. Open WhatsApp only on evidence that a paying segment needs it, and then without a payment method so the 1,000-message free tier is a hard cap.
5. **Stay on `gmail.send` and drafts.** Reading the owner's mailbox by API is fine for one user; offering mailbox reading to customers triggers an annual security assessment whose cost is disputed ($500 to $75,000 in vendor estimates). Do not put that on the roadmap before revenue.
6. **Make the CRM a mirror, not a dependency.** Own table first; HubSpot Free as an optional view. De-prioritise the multi-tenant HubSpot OAuth work (T-552 scope) until a customer asks to connect a portal.
7. **Set up e-mail hygiene once, now.** SPF, DKIM, DMARC with reporting, Postmaster Tools, one-click unsubscribe, separate subdomain for anything that is not transactional. It costs nothing and it is the only part of deliverability that cannot be fixed after a bad start.
8. **Treat OLX as optional.** It depends on a third party's approval and has no product to carry yet.
9. **Measure the funnel in its own units.** Views and subscribers are reach. A lead is a person who started the bot or left an e-mail with consent. Revenue is a received payment. Net profit is revenue minus provider fees, payment fees and taxes. At present all four after "reach" are zero, and every channel cost above $0 is a direct loss.
10. **First paid steps, in order of likely need:** Resend Pro at $20 per month (when 100 per day blocks real mail), then a custom-domain mailbox, then a shared inbox. Per-resolution AI support and cold-e-mail tooling come last and only against measured volume.

## Sources

No page could be opened in full (see the method note). The list below contains only pages whose content was returned by a search on 2026-11-17 and used above.

Official and primary (extracts from the official domain):
- https://core.telegram.org/bots
- https://core.telegram.org/bots/faq
- https://core.telegram.org/bots/api
- https://core.telegram.org/bots/api-changelog
- https://core.telegram.org/bots/features
- https://core.telegram.org/bots/webapps
- https://core.telegram.org/api/bots/connected-business-bots
- https://core.telegram.org/api/business
- https://core.telegram.org/constructor/businessBotRights
- https://core.telegram.org/api/obtaining_api_id
- https://core.telegram.org/api/auth
- https://core.telegram.org/api/stars
- https://core.telegram.org/api/layers
- https://telegram.org/tos/bot-developers
- https://telegram.org/privacy
- https://telegram.org/blog/telegram-stars
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/conversation-based-pricing
- https://developers.facebook.com/community/threads/1328420532772816/
- https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
- https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api
- https://ec.europa.eu/commission/presscorner/api/files/document/print/en/ip_26_1276/IP_26_1276_EN.pdf
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- https://developers.google.com/workspace/guides/configure-oauth-consent
- https://developers.google.com/workspace/gmail/imap/imap-smtp
- https://support.google.com/cloud/answer/13463817
- https://support.google.com/cloud/answer/13465431
- https://support.google.com/cloud/answer/13807380
- https://support.google.com/a/answer/166852
- https://support.google.com/a/answer/81126
- https://support.google.com/mail/answer/14229414
- https://support.google.com/mail/answer/14668346
- https://support.google.com/mail/answer/22839
- https://techcommunity.microsoft.com/blog/outlook/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730
- https://resend.com/pricing
- https://resend.com/docs/knowledge-base/account-quotas-and-limits
- https://resend.com/docs/knowledge-base/what-is-resend-pricing
- https://postmarkapp.com/pricing
- https://postmarkapp.com/support/article/1285-pricing-billing-faq
- https://aws.amazon.com/ses/pricing/
- https://aws.amazon.com/blogs/messaging-and-targeting/introducing-amazon-simple-email-service-ses-pricing-plans/
- https://www.brevo.com/features/email-api/
- https://www.brevo.com/free-smtp-server/
- https://www.brevo.com/products/transactional-email/
- https://www.hubspot.com/products/crm
- https://www.hubspot.com/products/crm/starter
- https://hubspot.com/pricing/sales
- https://www.hubspot.com/pricing/suite
- https://legal.hubspot.com/hubspot-product-and-services-catalog/technical-limits
- https://developers.hubspot.com/docs/api/usage-details
- https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview
- https://community.hubspot.com/t5/Account-Settings/Contact-Limit-1000/td-p/1274101
- https://developer.olxgroup.com/terms-and-conditions
- https://developer.olxgroup.com/docs/terms-conditions
- https://developer.olxgroup.com/faq
- https://developer.olx.pl/swagger/20

Secondary (blogs, press, library documentation):
- https://grammy.dev/advanced/flood
- https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits
- https://www.flowcall.co/blog/whatsapp-business-api-pricing
- https://blueticks.co/blog/whatsapp-business-api-pricing-2026
- https://www.engagelab.com/blog/whatsapp-api-pricing
- https://setsmart.io/blog/whatsapp-business-api-pricing
- https://getkanal.com/blog/whatsapp-business-pricing-guide
- https://respond.io/blog/whatsapp-general-purpose-chatbots-ban
- https://dig.watch/updates/meta-changes-whatsapp-terms-to-block-third-party-ai-assistants
- https://www.alibabacloud.com/help/en/chatapp/use-cases/whatsapp-ai-policy-2026-guide
- https://gulfnews.com/technology/no-more-chatgpt-and-perplexity-on-whatsapp-meta-bans-major-ai-chatbots-from-2026-1.500316016
- https://decrypt.co/370580/eu-orders-meta-open-whatsapp-rival-ai-chatbots
- https://www.houthoff.com/insights/news/a-rare-show-offorce-commission-deploys-interim-measures-against-meta-to-safeguard-ai-competition/
- https://www.unipile.com/gmail-api-scopes-guide/
- https://truto.one/google.md
- https://redsift.com/tools/microsoft-sender-requirements
- https://mailtrap.io/blog/outlook-new-email-sender-requirements/
- https://thetechhacker.com/2026/11/14/best-transactional-email-api/
- https://www.buildmvpfast.com/api-costs/email
- https://smbdashboard.com/blog/hubspot-free-crm-limitations
- https://scalry.com/blogs/hubspot-free-crm-limits
- https://www.scopiousdigital.com/blog/hubspot-api-rate-limits-production
- https://www.taskrhino.ca/twenty-crm-implementation/twenty-crm-review/
- https://stackbinary.io/insights/twenty-crm-vs-attio-vs-hubspot
- https://makerstack.co/reviews/twenty-crm-review/
- https://opsily.com/hosting/twenty-crm/twenty-crm-cost
- https://marketbetter.ai/blog/attio-crm-pricing-breakdown-2026/
- https://coworker.ai/blog/attio-pricing
- https://fluidcrm.io/blog/attio-vs-pipedrive/
- https://www.folk.app/articles/pipedrive-vs-attio
- https://www.eesel.ai/blog/chatwoot-pricing
- https://selfhostoffice.com/pricing/chatwoot/
- https://achiya-automation.com/en/blog/chatwoot-pricing/
- https://www.dragapp.com/blog/crisp-pricing/
- https://www.featurebase.app/blog/crisp-pricing
- https://www.eesel.ai/blog/crisp-pricing
- https://www.featurebase.app/blog/plain-pricing
- https://unthread.io/blog/plain-pricing/
- https://www.getmacha.com/blog/plain-complete-guide
- https://www.eesel.ai/blog/a-complete-guide-to-zendesk-ai-agents-setup-costs-and-best-practices
- https://markaicode.com/pricing/zendesk-pricing/
- https://corepiper.com/blog/zendesk-ai-agent-pricing-2026/
- https://www.getmacha.com/blog/intercom-fin-pricing
- https://www.getmacha.com/blog/intercom-fin-ai-agent-complete-guide
- https://corebee.ai/blog/intercom-fin-pricing-real-math-2026
- https://aissist.io/insights/intercom-fin-review
- https://www.lemlist.com/blog/instantly-vs-smartlead
- https://moderninbound.com/blog/clay-vs-smartlead
- https://growth.cx/blog/instantly-vs-apollo-vs-smartlead/
- https://instantly.ai/blog/best-instantly-alternatives-outbound-sales/
- https://litemail.ai/blog/cold-email-tool-pricing-comparison-2026
- https://www.lemlist.com/blog/gdpr-cold-email
- https://asphia.consulting/blog/cold-email-gdpr-europe-2026/
- https://www.quarvio.io/blog/cold-email-gdpr-guide
- https://prospeo.io/s/gdpr-cold-email
- https://noobclaw.com/blog/linkedin-automation-rules-2026/
- https://www.revenueflow.com/blog/linkedin-web-scraping
- https://www.anybiz.io/blogs/linkedin-automation-what-actually-changed/
- https://sellinger.ai/blog/linkedin-terms-of-service-and-automation
- https://garazd.biz/en/blog/odoo-integration/odoo-olx-integration
- https://apify.com/studio-amba/olx-ua-scraper.md

Repository files read (local):
- /home/user/blackboxlab-factoryos/ROADMAP.md (T-700, T-701)
- /home/user/blackboxlab-factoryos/DECISIONS.md (2026-11-17 T-700; Resend default)
- /home/user/blackboxlab-factoryos/docs/research/oauth_providers.md (HubSpot section, via search match)

Hosts that returned a policy denial to WebFetch and would need to be allowed in the session's network settings for a full verification pass: core.telegram.org, developers.facebook.com, www.whatsapp.com, support.google.com, developers.google.com, developers.hubspot.com, fin.ai.
