# Payments, invoicing, tax and agent payment rights for a Ukraine-based solo AI business (state as of 2026-11-17/18)

Scope: how a Ukraine-resident solo founder (FactoryOS / Blackbox Lab) can take money, invoice, run subscriptions and refunds, keep books and pay tax, and how far payment rights can be delegated to AI agents. NOT LEGAL OR TAX ADVICE: every Ukrainian tax/currency point below must be confirmed by a local accountant (бухгалтер ФОП / ЗЕД).

Method note (honesty): the session proxy blocks WebFetch for all hosts except github.com / raw.githubusercontent.com / pypi.org. Only one page was opened in full (Polar docs on GitHub). Everything else was read through WebSearch extracts restricted to the official domain where possible; such facts are labelled "search extract of <URL>". Facts from my training knowledge (cut-off June 2026) that I could not re-verify are labelled "[training, unverified]".

## Key claims

| # | Claim | Source URL | Date/version | Confidence |
|---|---|---|---|---|
| 1 | Stripe does not serve businesses located in Ukraine (also Russia, Belarus); a Ukrainian FOP cannot open a Stripe merchant account directly. | https://support.stripe.com/questions/sanctions-on-russia-and-belarus ; https://docs.stripe.com/tax/supported-countries | page current at 2026-11 (search extract) | verified_primary (search extract) |
| 2 | Lemon Squeezy closed new store sign-ups on 2026-11-16 and stops processing payments and renewals on 2027-03-31; migration path is Stripe Managed Payments, only for sellers in Managed-Payments countries. Not an option for FactoryOS. | https://www.lemonsqueezy.com/blog/saying-goodbye-to-lemon-squeezy ; https://docs.lemonsqueezy.com/migration | 2026-11-16 | verified_primary (search extract) |
| 3 | Stripe Managed Payments (Stripe's MoR) costs 3.5% per successful transaction on top of standard Stripe processing, is GA for businesses in 39 countries (changelog 2026-04-22), requires the seller to be based in a supported location and only covers fully automated digital products. Ukraine-based sellers are excluded because Stripe itself excludes Ukraine. | https://support.stripe.com/questions/managed-payments-pricing ; https://docs.stripe.com/payments/managed-payments/eligibility ; https://docs.stripe.com/payments/managed-payments/changelog | 2026-04-22 changelog; pages current 2026-11 | verified_primary (search extract) + inference for Ukraine |
| 4 | Polar pays sellers only via Stripe Connect Express in a fixed list of countries; Ukraine is NOT on the list. | https://github.com/polarsource/polar/blob/main/docs/merchant-of-record/supported-countries.mdx | main branch, fetched 2026-11-18 | verified_primary |
| 5 | Creem (MoR, 3.9% + 40c per transaction) lists Ukraine among supported merchant countries with local bank transfer payouts (payout fee 7 EUR/USD or 1%, whichever higher). | https://docs.creem.io/merchant-of-record/supported-countries ; https://www.creem.io/ | 2026-11 (search extract) | verified_primary (search extract) for listing; vendor_claim for fee |
| 6 | Paddle (MoR) charges 5% + 50c per checkout transaction, pays out monthly by wire or Payoneer (min $100; $15 SWIFT fee in some countries); its unsupported list names occupied Ukrainian regions (Crimea, Donetsk, Kherson, Luhansk, Zaporizhzhia), not Ukraine as a whole. | https://www.paddle.com/pricing ; https://www.paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid ; https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle | pricing current 2026-11; country help page is old (~2022) | verified_primary (search extract); Ukraine seller eligibility = inference |
| 7 | Dodo Payments: Ukraine is on its prohibited list and only "grandfathered" merchants already onboarded continue under enhanced monitoring -> new Ukrainian merchants are likely not accepted. | https://docs.dodopayments.com/miscellaneous/accepted-countries-and-territories | 2026-11 (search extract) | verified_primary (search extract) |
| 8 | Ukrainian FOP single tax group 3 in 2026: 5% of income (or 3% + VAT), military levy 1% of income, annual income limit 10,091,049 UAH (1,167 minimum wages, fixed at 01.01.2026); excess taxed at 15% and forces a move to the general system. | https://services.dtkt.ua/catalogues/tax_rates/173-jedinii-podatok-v-ukrayini-u-2026-roci ; https://dn.tax.gov.ua/media-ark/news-ark/984053.html | 2026 | reported_secondary (accounting press + regional DPS page, search extract) |
| 9 | Mandatory VAT for single-tax FOPs above 1M UAH turnover from 2027 is a Minfin draft (published 2025-12-18; a March-2026 revision discussed a 4M UAH threshold); as of ~June 2026 it was not submitted to the Rada. No evidence found that it was adopted by Nov 2026. | https://news.dtkt.ua/taxation/pdv/106369-oboviazkova-rejestraciia-platnikami-pdv-z-2027-roku-dlia-jedinnikiv-1-3-grup-projekt-zakonu-vid-minfinu ; https://newframelegal.com/article/pdv-dlya-fop-yedynnykiv-2027 | 2025-12-18 / ~2026-06 | reported_secondary |
| 10 | monobank internet acquiring: 1.3% for Ukrainian cards, 2% for foreign cards; requires FOP/TOV account at monobank (comparison page by monobank itself). | https://monobank.ua/compare/internet-acquiring ; https://monobank.ua/en/acquiring | 2026 (search extract) | vendor_claim |
| 11 | EU AI Act Art. 50 transparency duties (incl. telling people they interact with an AI system from the first interaction) apply from 2026-08-02; the Digital Omnibus (in force 2026-07-27) gave a grace period to 2026-12-02 only for machine-readable marking of output (Art. 50(2)) for systems placed on the market before 2026-08-02, not for chatbot disclosure. | https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act ; https://artificialintelligenceact.eu/ai-act-explorer/digital-omnibus/ | 2026-07/08 | verified_primary (search extract) |
| 12 | Stripe "Issuing for agents" (per-agent cards, spend limits, MCC allowlists, real-time authorization webhook) and Issuing MCP card management are private preview; Stripe recommends restricted API keys for agents; Link wallet for agents requires a person to approve each credential share. Requires a Stripe account, so unavailable to a Ukrainian FOP. | https://docs.stripe.com/issuing/agents ; https://docs.stripe.com/keys/restricted-api-keys ; https://stripe.com/blog/giving-agents-the-ability-to-pay | 2026 (search extract) | verified_primary (search extract); Ukraine = inference |
| 13 | ChatGPT Instant Checkout / ACP: protocol is open, but Instant Checkout is available to approved partners; launch scope was US Etsy sellers with Shopify to follow; Stripe's agentic checkout product is for US sellers. | https://developers.openai.com/commerce/specs/checkout ; https://openai.com/index/buy-it-in-chatgpt/ ; https://stripe.com/sessions/2026/agentic-commerce-under-the | 2025-09 launch; 2026 session | verified_primary (search extract) |
| 14 | x402 is live; Coinbase CDP facilitator: first 1,000 settlements/month free, then $0.001 each; settles on Base, Polygon, Arbitrum, Monad, World, Solana. AP2: published spec, no independently confirmed production card deployment as of Oct 2026 (secondary). | https://docs.cdp.coinbase.com/x402/support/faq ; https://docs.cdp.coinbase.com/x402/core-concepts/facilitator ; https://protofire.io/guides/agentic-payment-protocols/ | 2026 | verified_primary (x402); reported_secondary (AP2) |
| 15 | Ukraine has no crypto tax/regulatory regime in force: Law 2074-IX "On Virtual Assets" (Feb 2022) never entered into force; bill 10225-d passed first reading 2025-09-03, Finance Committee backed it in Nov 2026; if adopted, reported effective date 2027-07-01. | https://finance.liga.net/en/cryptoeconomics/novosti/ukraine-to-tax-profits-from-cryptocurrencies-draft-law-passes-first-reading ; https://dev.ua/en/news/pidtrymav-zakonoproiekt-virtualni-aktyvy | 2025-09 / 2026-11 | reported_secondary |

## Detailed findings

### 1. Stripe and "foreign company" routes

Takeaway: Stripe is closed to a Ukraine-located business; using Stripe means creating and running a foreign company, which contradicts "zero additional spend" before any revenue exists.

Cited findings
- Stripe "does not currently serve users located in Russia, Ukraine and Belarus"; Stripe Tax docs list Ukraine as unsupported for business location — search extract of https://support.stripe.com/questions/sanctions-on-russia-and-belarus and https://docs.stripe.com/tax/supported-countries.
- Stripe Tax can collect Ukrainian VAT on digital services for remote (foreign) sellers; Ukraine registration threshold for non-resident e-service suppliers 1,000,000 UAH/previous year — search extract of https://docs.stripe.com/tax/supported-countries/europe/ukraine. (Relevant only if FactoryOS ever sells via a foreign entity to Ukrainian consumers.)
- Stripe Atlas: founders "from anywhere in the world" can form a Delaware company; Atlas terms restrict only the Crimean region of Ukraine — search extract of https://docs.stripe.com/atlas and https://stripe.com/legal/atlas. Atlas price (historically $500 one-time + registered agent fee after year 1) was NOT verified in this round [training, unverified].
- Mercury: non-US founders can apply but the company must be US-formed with some US operations; it cannot serve businesses with founders/financial controllers resident in restricted countries; restriction is by residence, not citizenship. Whether Ukraine is on the list was NOT verified — search extract of https://support.mercury.com/hc/en-us/articles/28770467511060-Eligibility and https://mercury.com/faq.

Inferences
- A US LLC/Estonian OÜ/UK Ltd costs real money every year (formation, registered agent, US Form 5472 filings for foreign-owned single-member LLCs [training, unverified], Estonian accounting, UK Companies House filings) and creates Ukrainian controlled-foreign-company (КІК) reporting duties and "place of effective management" risk for a Ukrainian tax resident [training, unverified — accountant]. With zero revenue this is negative-EV; revisit only if a specific buyer segment demonstrably requires Stripe (e.g. US B2B procurement) or revenue exceeds what an MoR can handle.

Gaps
- Current Atlas price, Mercury restricted-country list for Ukraine, Wise Business availability for Ukrainian residents — not verified (searches returned no primary extract).

### 2. Merchant-of-record (MoR) providers for a Ukrainian seller

Takeaway: Paddle and Creem are the realistic MoR options for a Ukraine-based FOP selling digital subscriptions internationally; Lemon Squeezy is closing, Polar and Stripe Managed Payments exclude Ukraine, Dodo appears closed to new Ukrainian merchants, Gumroad pays non-direct-deposit countries via PayPal only.

Cited findings
- Lemon Squeezy: blog post dated 2026-11-16 — new sign-ups closed, payments and subscription renewals stop 2027-03-31, no extension; migration tooling to Stripe Managed Payments from 2026-12-02; sellers in non-MP countries must export data and leave — search extract of https://www.lemonsqueezy.com/blog/saying-goodbye-to-lemon-squeezy and https://docs.lemonsqueezy.com/migration. Migrating merchants get a promotional 1.5% MP fee through 2027-12-01 (same extract).
- Stripe Managed Payments: 3.5% per successful transaction, calculated on the full amount incl. tax, plus standard processing; Billing fees separate — search extract of https://support.stripe.com/questions/managed-payments-pricing. GA for businesses in 39 countries (changelog 2026-04-22); seller must be based in a supported location; Connect/Express accounts excluded; only fully automated digital products (not human-delivered services); tax handled in 80+ countries (other Stripe pages say 75+) — search extract of https://docs.stripe.com/payments/managed-payments/eligibility and https://docs.stripe.com/payments/managed-payments/changelog.
- Polar: payouts only via Stripe Connect Express in listed countries; list includes Moldova, Poland, Kazakhstan, Uzbekistan, etc. but not Ukraine; "all payments from customers are made to Polar (US)" — opened https://github.com/polarsource/polar/blob/main/docs/merchant-of-record/supported-countries.mdx. Polar adds no payout markup; Stripe payout costs apply ($2/month active, 0.25% + $0.25 per payout, FX 0.25–1%) — search extract of https://polar.sh/docs/features/finance/payouts.
- Paddle: 5% + 50c per checkout transaction (pay-as-you-go; custom for volume) — search extract of https://www.paddle.com/pricing. Payout monthly via wire or Payoneer, threshold $100 (adjustable), $15 SWIFT fee for certain countries, Payoneer fees per Payoneer account — search extract of https://www.paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid and https://www.paddle.com/help/manage/get-paid/is-there-a-fee-taken-for-payouts. Paddle "works with software businesses anywhere in the world" except an unsupported list (sanctions/AML) that includes the occupied Ukrainian regions — search extract of https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle (page is old, ~2022). Ukraine listed as a buyer country (UAH display, VAT 20% B2C) — search extract of https://developer.paddle.com/concepts/sell/supported-countries-locales.md and https://www.paddle.com/help/sell/tax/which-countries-does-paddle-charge-sales-tax-or-vat-for.
- Creem: supports merchants in 87 countries (another table says 86), Ukraine listed with local bank transfer payouts; payout fee 7 EUR/USD or 1% (higher) — search extract of https://docs.creem.io/merchant-of-record/supported-countries. Fee 3.9% + 40c, no monthly fee — vendor claim at https://www.creem.io/.
- Dodo Payments: Ukraine among countries "grandfathered" under enhanced monitoring after being added to the prohibited list; payouts only to listed countries; payout $5 under $1,000; USD SWIFT for non-US businesses $25 — search extract of https://docs.dodopayments.com/miscellaneous/accepted-countries-and-territories and https://docs.dodopayments.com/miscellaneous/pricing-and-fee-structure.
- Gumroad: 10% + 50c direct sales, 30% via Discover — search extract of https://gumroad.com/pricing; outside direct-deposit countries payouts only via verified PayPal in USD; min payout $10 — search extract of https://help.gumroad.com/article/13-getting-paid (old pages). Whether Ukraine has direct deposit: not found.
- FastSpring: not researched in this round (gap).

What an MoR covers (from provider docs above): the MoR is the legal seller to the end customer, collects/remits VAT/GST/sales tax in its covered jurisdictions, runs checkout, subscriptions, dunning, refunds and chargebacks, then pays the vendor. This removes EU VAT OSS registration for the founder (Stripe MP: "handles sales tax, VAT, GST in 80+ countries" — search extract of https://docs.stripe.com/payments/managed-payments/tax-compliance).

Worked fee example (inference, assumptions stated): 100 subscribers x $10/month = $1,000 gross card revenue.
- Paddle: 5% + $0.50 x 100 = $100 fees (10% effective at a $10 price point) + possibly $15 SWIFT -> ~$885 payout.
- Creem: 3.9% + $0.40 x 100 = $79 + payout fee max($7, 1%) ~ $9 -> ~$912 payout.
- Gumroad: 10% + $0.50 x 100 = $150 -> ~$850 (+PayPal withdrawal costs).
- Then FOP group 3: 5% single tax + 1% military levy on the UAH-equivalent income (~$53 on $885), plus fixed ESV (see section 4, ~1,902 UAH/month ~ $45 at an assumed ~42 UAH/USD [rate unverified]).
- Net before own costs: roughly $790–$815 of $1,000. Low price points are punished by the fixed per-transaction cents: a $5 plan loses ~14% to Paddle alone.
- Metric discipline: views and followers are not subscribers; trial sign-ups are leads; only settled MoR payouts net of refunds/chargebacks are revenue; net profit additionally subtracts taxes, ESV, API/provider spend and the founder's time.

Inferences
- Paddle's acceptance depends on product review (software/digital products; AI-content and "wrapper" products may be scrutinised) — not verified in this round; apply and expect possible rejection. Creem is a younger company; counterparty risk (cf. Lemon Squeezy shutdown after its acquisition) argues for keeping customer/subscription data exportable and webhooks mirrored into FactoryOS's own ledger.

Gaps
- Paddle's current written seller eligibility for Ukraine (old help page), Creem's footnote on Ukraine, Gumroad direct deposit for Ukraine, FastSpring.

### 3. Ukrainian payment rails (domestic customers, B2B, Telegram, crypto)

Takeaway: for Ukrainian customers, monobank/LiqPay acquiring at ~1.3% (2% foreign cards) on a FOP account is cheap and API-driven; for foreign B2B clients, an invoice paid by SWIFT to a FOP currency account or via Payoneer is the zero-setup path; Telegram Stars and crypto are poor fits.

Cited findings
- monobank (plata by mono) internet acquiring: 1.3% domestic cards, 2% international; requires FOP/TOV account in monobank; offers a free PRRO (software cash register) solution; temporary 0%-for-30-days promos — search extract of https://monobank.ua/compare/internet-acquiring and https://monobank.ua/en/acquiring (vendor's own comparison page).
- LiqPay (PrivatBank): same comparison lists 1.3%/2%; independent blogs give conflicting figures (1.5%, 2.75%) — search extract of https://monobank.ua/compare/internet-acquiring and secondary https://stexsoft.com/blog/monobank-liqpay-wayforpay. WayForPay: blogs quote 1.5–2.9% depending on turnover; payout next business day — secondary, https://findme.in.ua/ua/articles/stripe-vs-liqpay-vs-wayforpay-vs-fondy-vs-monobank-sho-krashe-dlya-biznesu-v-ukrayini/. Official tariff pages for WayForPay, hutko, Fondy were not obtained (gap).
- Payoneer for Ukrainian FOPs: receive USD/EUR/GBP via local receiving details or Payoneer payment requests (invoices); withdrawal to a Ukrainian bank quoted as "up to 3% + possible conversion fee" (another Payoneer page: $1.50 or 2–2.75% with conversion); for transfers >= USD 5,000 banks request supporting documents (contract/invoice) — search extract of https://www.payoneer.com/resources/benefits-of-payoneer-for-ukrainian-business/ and https://www.payoneer.com/resources/how-to-withdraw-money-from-payoneer/ (vendor marketing; fees conflict).
- Telegram Stars: bots sell digital goods in currency "XTR"; revenue withdrawn through a Fragment page to a TON wallet via payments.getStarsRevenueWithdrawalUrl, requires 2FA, minimum 1,000 Stars, USD rate set by client config (stars_usd_withdraw_rate_x1000) — search extract of https://core.telegram.org/api/stars and https://core.telegram.org/method/payments.getStarsRevenueWithdrawalUrl. The large spread between Star purchase price and withdrawal rate, and a withdrawal hold period, are [training, unverified].
- Crypto: Law 2074-IX "On Virtual Assets" (Feb 2022) never entered into force; bill 10225-d passed first reading 2025-09-03 (246 votes); Finance Committee backed it (Nov 2026 report); proposed 18% PIT on gains (plus military levy), transitional 5% rate to end-2028 for previously acquired assets, reported effective 2027-07-01 if adopted — secondary: https://finance.liga.net/en/cryptoeconomics/novosti/ukraine-to-tax-profits-from-cryptocurrencies-draft-law-passes-first-reading , https://dev.ua/en/news/pidtrymav-zakonoproiekt-virtualni-aktyvy , https://www.licentium.io/post/ukraine-virtual-assets-law-bill-10225-d. Hryvnia is the only legal tender for payments inside Ukraine [training, unverified]; a FOP's single-tax income must be money, so crypto receipts create unresolved classification/currency-control issues (accountant).

Inferences
- Stablecoin/x402 acceptance is technically trivial but legally unsettled for a Ukrainian FOP until 10225-d is adopted and in force; it also cannot be booked cleanly as single-tax income. Do not build revenue on it in 2026–H1 2027.
- Telegram Stars only make sense if the product lives inside a Telegram bot and Telegram's rules force Stars for digital goods; the TON off-ramp adds crypto-legal ambiguity.

### 4. Tax and legal for a Ukrainian FOP (verify with an accountant)

Takeaway: FOP group 3 at 5% + 1% military levy on gross income, with a 10.09M UAH limit in 2026, is one of the lightest regimes available to a solo exporter of digital services; the main open risk is the planned VAT-for-FOP reform.

Cited findings
- Group 3 rate 5% (non-VAT) or 3% (VAT payer); military levy 1% of income; 2026 income limit 10,091,049 UAH = 1,167 minimum wages fixed at 01.01.2026; excess taxed at 15%; group 3 can only move to the general system — search extracts of https://services.dtkt.ua/catalogues/tax_rates/173-jedinii-podatok-v-ukrayini-u-2026-roci , https://news.dtkt.ua/simple/individual-single-tax/104793-perevishhennia-limitu-dlia-1-3-grup-jep-iak-uniknuti-v-2026-roci-i-shho-robiti-za-pku-v-razi-porusennia , https://dn.tax.gov.ua/media-ark/news-ark/984053.html.
- Currently, group 3 single-taxpayers are not obliged to register for VAT when exceeding 1M UAH while they stay on the simplified system; the general VAT registration threshold is 1M UAH (Tax Code art. 181.1) — same dtkt extracts.
- Minfin draft (2025-12-18): mandatory VAT registration from 2027-01-01 for groups 1–3 above 1M UAH, 20% VAT, ~660k payers, +40.1bn UAH budget; March-2026 revised concept discussed 4M UAH; as of ~June 2026 not adopted and not submitted to the Rada — https://news.dtkt.ua/taxation/pdv/106369-oboviazkova-rejestraciia-platnikami-pdv-z-2027-roku-dlia-jedinnikiv-1-3-grup-projekt-zakonu-vid-minfinu ; https://newframelegal.com/article/pdv-dlya-fop-yedynnykiv-2027 (search extracts). It is part of Ukraine's IMF-programme commitments [training, unverified].
- Arithmetic (inference): 10,091,049 / 1,167 = 8,647 UAH minimum wage in 2026; minimum ESV = 22% x 8,647 ~ 1,902 UAH/month (~22.8k UAH/year), payable even with zero income unless an exemption applies [training, unverified — check martial-law exemptions].
- Currency control: NBU Resolution No. 67 sets settlement deadlines (mostly 180 days, extended to 150/270 days for specific goods in 2026); no source found on whether/how deadlines apply to a FOP's export of services — search extracts of https://news.dtkt.ua/state/zed/114061-granicni-stroki-rozraxunkiv-za-eksportom-ta-importom-u-period-vojennogo-stanu-roziasnennia-nbu and https://kpmg.com/ua/uk/home/media/press-releases/2026/01/relaxation-of-currency-restrictions-by-the-national-bank-of-ukraine.html (gap).
- Diia.City (9% / 5% regimes) is a legal-entity regime with headcount and minimum-pay conditions [training, unverified]; not applicable to a solo FOP.

Needs a local accountant (explicit list)
1. Whether MoR payouts are FOP income at gross sale price or at net payout (the MoR is the buyer/reseller; typically income = amount received from the MoR — inference).
2. Whether "export of services/e-services to a foreign MoR" is allowed under group 3 KVED and how to document it (contract = MoR terms + invoice/self-billing statement; whether payment of an invoice substitutes for an act).
3. UAH conversion date/rate for foreign-currency income, currency account opening, any NBU settlement deadlines for services.
4. PRRO / fiscal receipts duty for domestic online card payments (monobank offers free PRRO).
5. ESV obligations and exemptions under martial law; quarterly single-tax declaration.
6. Status of the VAT-for-FOP law and Ukraine's own VAT on e-services sold to Ukrainian consumers by the FOP.
7. CFC/tax-residency consequences if a foreign entity is ever formed.

EU VAT: B2C digital services to EU consumers are taxed where the consumer lives; non-EU sellers would need non-Union OSS registration [training, unverified]; using an MoR removes this because the MoR is the seller of record (Stripe MP / Paddle docs above).

### 5. Automation: invoicing, subscriptions, refunds, reconciliation, bookkeeping

Takeaway: all realistic rails expose API + webhooks; FactoryOS should own an append-only ledger fed by provider webhooks and never hold execution keys for money-out without a human step.

Cited findings
- Paddle Billing exposes REST API objects (products, prices, customers, addresses, subscriptions) and webhooks such as subscription.imported — search extract of https://developer.paddle.com/api-reference/products/list-products/ and https://developer.paddle.com/webhooks/subscriptions/subscription-imported/.
- Stripe restricted keys are the recommended key type for agents, limiting blast radius — search extract of https://docs.stripe.com/keys/restricted-api-keys (pattern applicable to any provider offering scoped keys).
- Payoneer supports payment requests/invoices to clients — search extract of https://www.payoneer.com/resources/business/how-to-create-an-invoice-in-payoneer/.
- Ukrainian accounting tools (e.g. FOP bookkeeping services, bank-integrated tax declarations) were not researched in this round (gap).

Inferences
- Minimal stack at zero spend: MoR (Paddle or Creem) webhooks -> FactoryOS endpoint -> idempotent ledger table (event id as key) -> monthly reconciliation job (MoR payout report vs bank statement vs ledger) -> draft single-tax income book entries for the accountant. Bank statement import from monobank/PrivatBank APIs is plausible but unverified here.

### 6. Agentic payments, November 2026

Takeaway: agent payment infrastructure is real but either US-centric, private-preview, issuer/bank-side, or crypto; none of it is needed or usable by FactoryOS to earn its first revenue, and all money-out tools conflict with zero-spend.

Cited findings
- ACP / Instant Checkout: protocol open; Instant Checkout in ChatGPT available to approved partners; launch: US users buying from US Etsy sellers, Shopify merchants "coming soon", single-item purchases — search extracts of https://developers.openai.com/commerce/specs/checkout and https://openai.com/index/buy-it-in-chatgpt/. Stripe's agentic checkout available for US sellers via Dashboard (Stripe Sessions 2026) — search extract of https://stripe.com/sessions/2026/agentic-commerce-under-the. ACP Delegated Payment spec — https://developers.openai.com/commerce/specs/payment.
- Stripe Issuing for agents (private preview): per-agent cards, spending limits, allowed merchant categories, real-time authorization webhook to approve/decline each attempt; programmatic checkout converts the card into a scoped Shared Payment Token so the agent never sees the PAN; issuing a card via MCP does not by itself let an agent pay — search extracts of https://docs.stripe.com/issuing/agents , https://docs.stripe.com/issuing/agents/programmatic-checkout , https://docs.stripe.com/issuing/agents/mcp ; spend controls per authorization/monthly, category and country blocks — https://docs.stripe.com/issuing/controls/spending-controls. Link for agents: person approves each credential share — https://stripe.com/blog/giving-agents-the-ability-to-pay.
- AP2 (Google): announced with an A2A x402 extension described as production-ready for crypto — search extract of https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol; Protofire found no confirmed production AP2 card transaction as of Oct 2026 — https://protofire.io/guides/agentic-payment-protocols/ (secondary). A claim that AP2 was donated to the FIDO Alliance (Apr 2026) could not be verified.
- x402: Coinbase CDP facilitator 1,000 free settlements/month then $0.001; only successful settle calls billed; buyers sign USDC authorizations (no gas token); networks Base, Polygon, Arbitrum, Monad, World, Solana — search extracts of https://docs.cdp.coinbase.com/x402/support/faq and https://docs.cdp.coinbase.com/x402/core-concepts/facilitator. Transaction-count claims (e.g. "167M+ by Apr 2026") are secondary and unverified.
- Mastercard Agent Pay: Santander completed "Europe's first live end-to-end payment executed by an AI agent" in a controlled environment (2026-03-02); Mastercard says all its European issuers are network-enabled; Worldline/ING production agentic transaction with explicit consumer approval (June 2026) — search extracts of https://newsroom.mastercard.com/news/europe/en/newsroom/press-releases/en/2026/santander-and-mastercard-complete-europe-s-first-live-end-to-end-payment-executed-by-an-ai-agent and https://www.mastercard.com/mt/en/news-and-trends/press/2026/june/worldline-ing-mastercard-agentic-payment.html. Visa expanded "Agentic Ready" on 2026-11-17, citing Worldline live transactions across European markets — https://investor.visa.com/news/news-details/2026/Visa-Expands-Agentic-Ready-to-Help-Scale-Trusted-AI-Commerce-Globally/default.aspx. Skyfire, Payman: not researched (gap).

Inferences
- Card-network agent programmes are integrated by issuers/acquirers/large merchants; a solo Ukrainian FOP benefits only indirectly (if its MoR checkout later accepts agent-initiated payments).
- The one agent-payment rail a small non-US business can use without approval is x402/USDC, which collides with Ukraine's unsettled crypto law (section 3).

### 7. Governance: view / prepare / execute

Takeaway: AI cannot be a KYC'd account holder or legal party; every account is the founder's (or the FOP's), so the agent's rights must be a strict subset, with execution of money movement gated by a human.

Cited findings
- KYC/identity: merchant/payout accounts are opened by the legal person (FOP = the founder as an individual entrepreneur); Mercury restricts by the residence of founders/financial controllers — search extract of https://support.mercury.com/hc/en-us/articles/28770467511060-Eligibility. Stripe's own agent products keep a human approval in the loop (Link) or programmatic spend controls set by the account owner (Issuing) — sources in section 6.
- Disclosure: from 2026-08-02 people interacting with an AI system must be informed from the first interaction (Art. 50); deepfake/AI-generated text duties for deployers also apply; omnibus grace to 2026-12-02 only for Art. 50(2) marking of pre-existing systems; the Code of Practice on AI-generated content (June 2026) is voluntary — search extracts of https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act and https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content.
- Consumer refunds: EU 14-day withdrawal right for digital content is lost only with the consumer's prior express consent and acknowledgement (Consumer Rights Directive 2011/83/EU) [training, unverified]; with an MoR, the MoR's buyer terms and refund policy govern.

Proposed permission matrix (inference)
| Right | Agent may do autonomously | Needs human confirmation (Telegram approve) | Never |
|---|---|---|---|
| View | read webhooks, payouts, balances, subscription states into ledger; produce daily revenue report (subscribers, MRR, refunds, chargebacks, net payout) | — | read bank passwords, 2FA, .env |
| Prepare | draft invoices, draft refund decisions, draft price changes, draft customer replies (with AI disclosure) | sending any invoice to a new counterparty; any price/plan change | — |
| Execute (money in) | create checkout links for existing approved prices; issue refunds under a policy (e.g. <= one billing period, <= $X, within 14 days, once per customer, idempotency key = order id) | refunds above policy, partial/credit deals, chargeback responses | change payout bank details |
| Execute (money out) | — | every payment, every new subscription/paid API, every card issuance | auto-top-ups, storing card PANs, crypto transfers |

Pre-authorisable by policy: low-value refunds within a published policy, dunning emails, subscription cancellations at customer request, retries of failed webhooks (idempotent). Must stay human: payouts, payout-account changes, any spend, contract/price commitments, chargeback evidence submission, anything touching tax filings.

## Counter-evidence and caveats

- Most facts come from search extracts, not opened pages (proxy restriction); the Paddle country page and Gumroad payout pages are years old; Paddle seller acceptance of a Ukrainian FOP is inferred from an exclusion list, not from a positive statement.
- Ukrainian PSP fees come mainly from monobank's own comparison page (a competitor-written comparison) and blogs with conflicting numbers (LiqPay 1.3% vs 1.5% vs 2.75%).
- Group 3 tax figures come from accounting press and a regional DPS news page, not the Tax Code text; the VAT-for-FOP reform status after June 2026 is unknown — it may have moved in the Rada in autumn 2026.
- Lemon Squeezy's fate is a counterweight to choosing small/young MoRs (Creem, Dodo): vendor shutdown or policy change (Dodo moving Ukraine to its prohibited list) can cut revenue with a few months' notice.
- MoRs are not cheaper: at low price points 8–15% of gross can go to MoR fees; a Ukrainian domestic acquirer at 1.3% is far cheaper but only for Ukrainian customers and puts consumer-law/VAT/fiscal-receipt duties on the FOP.
- Agentic payment "production" claims are mostly network/issuer press releases describing controlled transactions; adoption volumes are not public.
- AI Act article numbering in the Commission FAQ is inconsistent (chatbot duty referenced as 50(1) and 50(2)); final omnibus text not checked in the Official Journal.
- Nothing here says the founder already has a FOP; if not, registering one creates a fixed monthly ESV liability (~1,902 UAH) from day one even with zero revenue [training, unverified exemptions].

## Implications for FactoryOS

1. No company abroad, no Stripe, no Atlas before revenue. It costs money every year, adds CFC reporting, and gives nothing an MoR does not already give a first product.
2. Revenue rail for international digital products (MyCast/MyBrief subscriptions): apply to Paddle first (5% + 50c, wire/Payoneer payout, mature subscriptions/refunds/chargebacks API); Creem as fallback (lists Ukraine; 3.9% + 40c). Do not use Lemon Squeezy (closing 2027-03-31), Polar (no Ukraine payouts), Stripe Managed Payments (Stripe excludes Ukraine). Treat Dodo as unavailable for new Ukrainian merchants. Price at >= $9–10/month or annual plans to keep fixed per-transaction cents below ~10%.
3. Revenue rail for Ukrainian customers: monobank acquiring (1.3% / 2%) with its free PRRO, only if a domestic product exists; it shifts consumer and fiscal duties to the FOP.
4. B2B services (if any): invoice + SWIFT to FOP currency account or Payoneer request; agent drafts, human sends.
5. Tax: FOP group 3 (5% + 1%) is the default; the founder must budget ESV and have an accountant confirm items 1–7 in section 4 before the first payout. Cost of an accountant is real money; a one-off consultation is the only spend I would argue is justified at first revenue.
6. Build next, inside existing FastAPI/DBOS: an MoR webhook receiver + idempotent revenue ledger + daily revenue report into Telegram that separates views, sign-ups (leads), active subscribers, gross revenue, MoR fees, refunds/chargebacks, payouts received, taxes due and net profit. A DBOS workflow per refund request (prepare -> human approve -> execute with idempotency key) fits the existing durable-engine rules.
7. Agent payment rights: View = autonomous; Prepare = autonomous drafts; Execute = only policy-bounded small refunds; all money-out = human approval in Telegram, consistent with the existing "mandatory human approval before any payment" rule. Do not pursue Stripe Issuing for agents, ACP, AP2, x402 or Visa/Mastercard agent programmes now: unavailable (Stripe/US), irrelevant (no spend allowed), or legally unsettled (crypto in Ukraine).
8. Compliance: add an AI disclosure at the start of every customer-facing AI conversation (EU AI Act Art. 50, applies since 2026-08-02) and label synthetic media; publish a refund policy consistent with the MoR's terms.
9. Sceptical verdict: payments are not the bottleneck. An MoR account (free to open) plus a ledger is enough to reach the first paying customer; the scarce resource is demand, not payment infrastructure. Spending engineering time on agentic-payment protocols before the first $1 of revenue is the "impressive architecture" trap.

## Sources

Opened in full (WebFetch)
- https://github.com/polarsource/polar/blob/main/docs/merchant-of-record/supported-countries.mdx (Polar payout countries; fetched 2026-11-18)

Read only through search extracts (official domains unless marked secondary)
- https://support.stripe.com/questions/sanctions-on-russia-and-belarus
- https://docs.stripe.com/tax/supported-countries ; https://docs.stripe.com/tax/supported-countries/europe/ukraine
- https://docs.stripe.com/atlas ; https://stripe.com/legal/atlas
- https://support.mercury.com/hc/en-us/articles/28770467511060-Eligibility ; https://mercury.com/faq
- https://www.lemonsqueezy.com/blog/saying-goodbye-to-lemon-squeezy ; https://docs.lemonsqueezy.com/migration
- https://support.stripe.com/questions/managed-payments-pricing ; https://docs.stripe.com/payments/managed-payments/eligibility ; https://docs.stripe.com/payments/managed-payments/changelog ; https://docs.stripe.com/payments/managed-payments/tax-compliance
- https://polar.sh/docs/features/finance/payouts
- https://www.paddle.com/pricing ; https://www.paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid ; https://www.paddle.com/help/manage/get-paid/is-there-a-fee-taken-for-payouts ; https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle ; https://developer.paddle.com/concepts/sell/supported-countries-locales.md ; https://www.paddle.com/help/sell/tax/which-countries-does-paddle-charge-sales-tax-or-vat-for ; https://developer.paddle.com/webhooks/subscriptions/subscription-imported/
- https://docs.creem.io/merchant-of-record/supported-countries ; https://www.creem.io/
- https://docs.dodopayments.com/miscellaneous/accepted-countries-and-territories ; https://docs.dodopayments.com/miscellaneous/pricing-and-fee-structure
- https://gumroad.com/pricing ; https://help.gumroad.com/article/13-getting-paid
- https://monobank.ua/compare/internet-acquiring ; https://monobank.ua/en/acquiring
- secondary: https://stexsoft.com/blog/monobank-liqpay-wayforpay ; https://findme.in.ua/ua/articles/stripe-vs-liqpay-vs-wayforpay-vs-fondy-vs-monobank-sho-krashe-dlya-biznesu-v-ukrayini/
- https://www.payoneer.com/resources/benefits-of-payoneer-for-ukrainian-business/ ; https://www.payoneer.com/resources/how-to-withdraw-money-from-payoneer/ ; https://www.payoneer.com/resources/business/how-to-create-an-invoice-in-payoneer/
- https://core.telegram.org/api/stars ; https://core.telegram.org/method/payments.getStarsRevenueWithdrawalUrl
- secondary: https://finance.liga.net/en/cryptoeconomics/novosti/ukraine-to-tax-profits-from-cryptocurrencies-draft-law-passes-first-reading ; https://dev.ua/en/news/pidtrymav-zakonoproiekt-virtualni-aktyvy ; https://www.licentium.io/post/ukraine-virtual-assets-law-bill-10225-d
- https://dn.tax.gov.ua/media-ark/news-ark/984053.html ; secondary: https://services.dtkt.ua/catalogues/tax_rates/173-jedinii-podatok-v-ukrayini-u-2026-roci ; https://news.dtkt.ua/simple/individual-single-tax/104793-perevishhennia-limitu-dlia-1-3-grup-jep-iak-uniknuti-v-2026-roci-i-shho-robiti-za-pku-v-razi-porusennia ; https://news.dtkt.ua/taxation/pdv/106369-oboviazkova-rejestraciia-platnikami-pdv-z-2027-roku-dlia-jedinnikiv-1-3-grup-projekt-zakonu-vid-minfinu ; https://newframelegal.com/article/pdv-dlya-fop-yedynnykiv-2027 ; https://news.dtkt.ua/state/zed/114061-granicni-stroki-rozraxunkiv-za-eksportom-ta-importom-u-period-vojennogo-stanu-roziasnennia-nbu ; https://kpmg.com/ua/uk/home/media/press-releases/2026/01/relaxation-of-currency-restrictions-by-the-national-bank-of-ukraine.html
- https://developers.openai.com/commerce/specs/checkout ; https://developers.openai.com/commerce/specs/payment ; https://openai.com/index/buy-it-in-chatgpt/ ; https://stripe.com/sessions/2026/agentic-commerce-under-the
- https://docs.stripe.com/issuing/agents ; https://docs.stripe.com/issuing/agents/programmatic-checkout ; https://docs.stripe.com/issuing/agents/mcp ; https://docs.stripe.com/issuing/controls/spending-controls ; https://docs.stripe.com/keys/restricted-api-keys ; https://stripe.com/blog/giving-agents-the-ability-to-pay
- https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol ; secondary: https://protofire.io/guides/agentic-payment-protocols/
- https://docs.cdp.coinbase.com/x402/support/faq ; https://docs.cdp.coinbase.com/x402/core-concepts/facilitator
- https://newsroom.mastercard.com/news/europe/en/newsroom/press-releases/en/2026/santander-and-mastercard-complete-europe-s-first-live-end-to-end-payment-executed-by-an-ai-agent ; https://www.mastercard.com/mt/en/news-and-trends/press/2026/june/worldline-ing-mastercard-agentic-payment.html ; https://investor.visa.com/news/news-details/2026/Visa-Expands-Agentic-Ready-to-Help-Scale-Trusted-AI-Commerce-Globally/default.aspx
- https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act ; https://artificialintelligenceact.eu/ai-act-explorer/digital-omnibus/ ; https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content
