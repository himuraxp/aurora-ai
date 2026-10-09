# Infomaniak MCP Server

MCP server for the [Infomaniak API](https://developer.infomaniak.com/docs/api) — exposes **577 endpoints** across **15 categories** with **168 dedicated tools** + **1 generic tool**.

## Overview

The Infomaniak API is RESTful, uses OAuth2 Bearer authentication, and covers:

| Category | Endpoints | Dedicated Tools | Description |
|----------|-----------|----------------|-------------|
| **Core** | 48 | 48 | Events, profile, accounts, teams, kSuite, mailboxes, products, actions, async tasks |
| **AI** | 16 | 16 | LLM chat/completions, embeddings, rerank, image generation, transcription, batch results |
| **VOD** | 412 | 15 | Video on Demand — channels, media, encodings, statistics, folders, playlists, shares |
| **Newsletter** | 77 | 67 | Campaigns, subscribers, groups, segments, fields, templates, webforms, dashboard, credits |
| **DNS** | 11 | 11 | Zones and DNS records CRUD |
| **Utils** | 15 | 10 | URL shortener, countries, languages, timezones |
| **Generic** | 577 | 1 | `infomaniak_api_call` — covers all endpoints not exposed by dedicated tools |
| **Total** | **577** | **168 + 1** | |

## Installation

### Prerequisites

- Node.js 18+
- An Infomaniak API token (get one at [manager.infomaniak.com](https://manager.infomaniak.com/v3/ng/accounts/token/list))

### Build

```bash
cd mcp/infomaniak
npm install
npm run build
```

### Configuration

> **Security (2026-10-07, S-02) — read-only by default**: mutating methods (POST/PUT/PATCH/DELETE)
> are refused at the HTTP client level unless `INFOMANIAK_MCP_ALLOW_WRITES=1` is set. The gate keys
> on the real HTTP method, not on tool names, so no naming convention can bypass it. Writes are
> performed through the **orchestrator-only bridge plugin**
> (`config/plugins/infomaniak-bridge.ts` → tool `infomaniak_api_call`), following the
> aurora-memory bridge model (ADR-021): broad reads for every agent, writes behind an explicit
> orchestrator decision. Verify with `scripts/check-infomaniak-write-gate.mjs` (wired into
> `health-check.sh`).

Add to `opencode.json`:

```json
{
  "mcp": {
    "infomaniak": {
      "type": "local",
      "command": ["node", "/path/to/mcp/infomaniak/dist/index.js"],
      "enabled": true,
      "timeout": 30000,
      "env": {
        "INFOMANIAK_API_TOKEN": "{env:INFOMANIAK_API_TOKEN}",
        "INFOMANIAK_MCP_ALLOW_WRITES": "0"
      }
    }
  }
}
```

Set the token in `~/.config/opencode/.env`:

```
INFOMANIAK_API_TOKEN=
```

Or run `setup.sh` which collects it interactively.

## Architecture

```
mcp/infomaniak/
├── package.json
├── tsconfig.json
├── src/
│   ├── client.ts            # HTTP client (auth, rate limit, pagination)
│   ├── types.ts              # Shared ToolDef type
│   ├── index.ts              # MCP server entry point (stdio transport)
│   └── modules/
│       ├── core.ts           # 48 tools — events, profile, accounts, teams
│       ├── ai.ts             # 16 tools — LLM, embeddings, images, rerank
│       ├── dns.ts            # 11 tools — zones, records
│       ├── utils.ts          # 10 tools — url shortener, reference data
│       ├── newsletter.ts     # 67 tools — campaigns, subscribers, groups
│       ├── vod.ts            # 15 tools — channels, media, statistics
│       └── generic.ts        # 1 tool  — infomaniak_api_call (all 577 endpoints)
└── dist/                     # Compiled JS
```

### Client (`client.ts`)

- **Base URL**: `https://api.infomaniak.com`
- **Auth**: Bearer token via `INFOMANIAK_API_TOKEN` env var
- **Rate limit**: 60 requests/min (queued automatically)
- **Pagination**: Supports `page`/`per_page` and `limit`/`skip` params
- **Error handling**: Parses `{ result: "error", error: { code, description } }` and throws

## Tools Reference

### Core (48 tools)

#### Events

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_events` | GET | `/2/events` | List all open events (maintenance, incidents) |
| `get_event` | GET | `/2/events/{event_id}` | Display a specific event |
| `get_public_cloud_status` | GET | `/2/events/public-cloud-status` | Get Public Cloud status |

#### Profile

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `get_profile` | GET | `/2/profile` | List user information |
| `update_profile` | PATCH | `/2/profile` | Update profile information |
| `update_avatar` | POST | `/2/profile/avatar` | Add or update profile avatar |
| `delete_avatar` | DELETE | `/2/profile/avatar` | Delete profile avatar |
| `list_phones` | GET | `/2/profile/phones` | List phones |
| `get_phone` | GET | `/2/profile/phones/{phone_id}` | Display a phone |
| `delete_phone` | DELETE | `/2/profile/phones/{phone_id}` | Delete a phone |
| `list_emails` | GET | `/2/profile/emails` | List emails |
| `get_email` | GET | `/2/profile/emails/{email_type}/{email_id}` | Display an email |
| `delete_email` | DELETE | `/2/profile/emails/{email_type}/{email_id}` | Delete an email |
| `list_app_passwords` | GET | `/2/profile/applications/passwords` | List application passwords |
| `create_app_password` | POST | `/2/profile/applications/passwords` | Create an application password |
| `get_app_password` | GET | `/2/profile/applications/passwords/{password_id}` | Display an application password |

#### Accounts

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_accounts` | GET | `/1/accounts` | List accounts |
| `get_account` | GET | `/1/accounts/{account_id}` | Display an account |
| `list_account_products` | GET | `/1/accounts/{account_id}/products` | List account's products |
| `list_account_services` | GET | `/1/accounts/{account_id}/services` | List services |
| `list_current_account_products` | GET | `/1/accounts/current/products` | List current account's products |
| `list_basic_teams` | GET | `/1/accounts/{account_id}/basic/teams` | List basic teams info |
| `list_account_tags` | GET | `/1/accounts/{account_id}/tags` | List account tags |
| `create_tag` | POST | `/1/accounts/{account}/tags` | Create a tag |
| `update_tag` | PUT | `/1/accounts/{account}/tags/{tag}` | Update a tag |
| `delete_tag` | DELETE | `/1/accounts/{account}/tags/{tag}` | Delete a tag |
| `list_users` | GET | `/2/accounts/{account}/users` | List users |
| `list_user_app_accesses` | GET | `/2/accounts/{account}/users/{user}/app_accesses` | List app accesses |

#### Teams

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_teams` | GET | `/1/accounts/{account}/teams` | List teams |
| `create_team` | POST | `/1/accounts/{account}/teams` | Create a team |
| `get_team` | GET | `/1/accounts/{account}/teams/{team}` | Get a team |
| `update_team` | PATCH | `/1/accounts/{account}/teams/{team}` | Update a team |
| `delete_team` | DELETE | `/1/accounts/{account}/teams/{team}` | Delete a team |
| `invite_user` | POST | `/1/accounts/{account}/invitations` | Invite a user |
| `cancel_invitation` | DELETE | `/1/accounts/{account}/invitations/{invitation}` | Cancel an invitation |

#### kSuite & Mailbox

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `get_my_ksuite` | GET | `/1/my_ksuite/{my_k_suite_id}` | Show MyKSuite |
| `get_current_ksuite` | GET | `/1/my_ksuite/current` | Current MyKSuite |
| `cancel_ksuite_unsubscribe` | POST | `/1/my_ksuite/{my_k_suite_id}/cancel_unsubscribe` | Cancel unsubscription |
| `list_mailboxes` | GET | `/2/profile/ksuites/mailboxes` | List linked mailboxes |
| `attach_mailbox` | POST | `/2/profile/ksuites/mailboxes` | Attach a mailbox |
| `set_primary_mailbox` | PUT | `/2/profile/ksuites/mailboxes/{mailbox_id}/set_primary` | Set primary mailbox |
| `update_mailbox_password` | PUT | `/2/profile/ksuites/mailboxes/{mailbox_id}/update_password` | Update mailbox password |
| `unlink_mailbox` | DELETE | `/2/profile/ksuites/mailboxes/{mailbox_id}` | Unlink a mailbox |

#### Products, Actions & Tasks

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_products` | GET | `/1/products` | List products |
| `list_actions` | GET | `/1/actions` | List available actions |
| `get_action` | GET | `/1/actions/{action_id}` | Display an action |
| `list_tasks` | GET | `/1/async/tasks` | List async tasks |
| `get_task` | GET | `/1/async/tasks/{task_uuid}` | Display a task |

---

### AI (16 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_ai_apis` | GET | `/1/ai` | List all your LLM APIs |
| `list_ai_consumptions` | GET | `/1/ai/{product_id}/consumptions` | List API consumptions |
| `list_ai_models` | GET | `/2/ai/{product_id}/openai/v1/models` | List available models (v2) |
| `list_ai_models_legacy` | GET | `/1/ai/models` | List models (v1 legacy) |
| `list_ai_models_deprecated` | GET | `/1/ai/{product_id}/openai/models` | List models (deprecated) |
| `create_chat_completion` | POST | `/2/ai/{product_id}/openai/v1/chat/completions` | Create a chat completion |
| `create_completion` | POST | `/2/ai/{product_id}/openai/v1/completions` | Create a completion |
| `create_embeddings` | POST | `/2/ai/{product_id}/openai/v1/embeddings` | Create embeddings |
| `create_rerank` | POST | `/2/ai/{product_id}/cohere/v2/rerank` | Create rerankings |
| `create_chat_completion_deprecated` | POST | `/1/ai/{product_id}/openai/chat/completions` | Chat completion (deprecated) |
| `create_transcription` | POST | `/1/ai/{product_id}/openai/audio/transcriptions` | Create audio transcription |
| `create_image` | POST | `/1/ai/{product_id}/openai/images/generations` | Generate an image |
| `create_embeddings_deprecated` | POST | `/1/ai/{product_id}/openai/v1/embeddings` | Create embeddings (deprecated) |
| `create_photo_maker` | POST | `/1/ai/{product_id}/images/generations/photo_maker` | Customize realistic photos |
| `get_batch_result` | GET | `/1/ai/{product_id}/results/{batch_id}` | Get async batch result |
| `download_batch_result` | GET | `/1/ai/{product_id}/results/{batch_id}/download` | Download batch output |

---

### DNS (11 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `show_zone` | GET | `/2/zones/{zone}` | Show a DNS zone |
| `update_zone` | PUT | `/2/zones/{zone}` | Update a zone |
| `store_zone` | POST | `/2/zones/{zone}` | Create a zone |
| `delete_zone` | DELETE | `/2/zones/{zone}` | Delete a zone |
| `zone_exists` | GET | `/2/zones/{zone}/exists` | Check if a zone exists |
| `list_dns_records` | GET | `/2/zones/{zone}/records` | List DNS records |
| `create_dns_record` | POST | `/2/zones/{zone}/records` | Create a DNS record |
| `get_dns_record` | GET | `/2/zones/{zone}/records/{record}` | Show a DNS record |
| `update_dns_record` | PUT | `/2/zones/{zone}/records/{record}` | Update a DNS record |
| `delete_dns_record` | DELETE | `/2/zones/{zone}/records/{record}` | Delete a DNS record |
| `check_dns_record` | GET | `/2/zones/{zone}/records/{record}/check` | Check a DNS record |

---

### Utils (10 tools)

#### URL Shortener

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_short_urls` | GET | `/1/url-shortener` | List short URLs (v1) |
| `create_short_url` | POST | `/1/url-shortener` | Create a short URL |
| `update_short_url` | PUT | `/1/url-shortener/{short_url_code}` | Update a short URL |
| `get_short_url_quota` | GET | `/1/url-shortener/quota` | Get URL shortener quota |

#### Reference Data

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_countries` | GET | `/1/countries` | List countries |
| `get_country` | GET | `/1/countries/{country_id}` | Display a country |
| `list_languages` | GET | `/1/languages` | List languages |
| `get_language` | GET | `/1/languages/{language_id}` | Display a language |
| `list_timezones` | GET | `/1/timezones` | List timezones |
| `get_timezone` | GET | `/1/timezones/{timezone_id}` | Display a timezone |

---

### Newsletter (67 tools)

#### Campaigns (14)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_campaigns` | GET | `/1/newsletters/{domain}/campaigns` | List all campaigns |
| `create_campaign` | POST | `/1/newsletters/{domain}/campaigns` | Create a campaign |
| `delete_campaigns_bulk` | DELETE | `/1/newsletters/{domain}/campaigns` | Bulk delete campaigns |
| `get_campaign` | GET | `/1/newsletters/{domain}/campaigns/{campaign}` | Get a campaign |
| `update_campaign` | PUT | `/1/newsletters/{domain}/campaigns/{campaign}` | Edit a campaign |
| `delete_campaign` | DELETE | `/1/newsletters/{domain}/campaigns/{campaign}` | Delete a campaign |
| `get_campaign_tracking` | GET | `/1/newsletters/{domain}/campaigns/{campaign}/tracking` | Get tracking info |
| `get_campaign_links_activity` | GET | `/1/newsletters/{domain}/campaigns/{campaign}/report/links` | Links activity |
| `get_campaign_subscribers_activity` | GET | `/1/newsletters/{domain}/campaigns/{campaign}/report/activity` | Subscribers activity |
| `duplicate_campaign` | POST | `/1/newsletters/{domain}/campaigns/{campaign}/duplicate` | Duplicate a campaign |
| `test_campaign` | POST | `/1/newsletters/{domain}/campaigns/{campaign}/test` | Test a campaign |
| `cancel_campaign` | PUT | `/1/newsletters/{domain}/campaigns/{campaign}/cancel` | Cancel a campaign |
| `schedule_campaign` | PUT | `/1/newsletters/{domain}/campaigns/{campaign}/schedule` | Schedule a campaign |
| `test_template_campaign` | POST | `/1/newsletters/{domain}/campaigns/template/{template_uuid}/test` | Test template campaign |

#### Subscribers (13)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_subscribers` | GET | `/1/newsletters/{domain}/subscribers` | List all subscribers |
| `create_subscriber` | POST | `/1/newsletters/{domain}/subscribers` | Create a subscriber |
| `delete_subscribers_bulk` | DELETE | `/1/newsletters/{domain}/subscribers` | Bulk delete subscribers |
| `count_subscribers_status` | GET | `/1/newsletters/{domain}/subscribers/count_status` | Count subscribers by status |
| `get_subscriber` | GET | `/1/newsletters/{domain}/subscribers/{subscriber}` | Fetch a subscriber |
| `update_subscriber` | PUT | `/1/newsletters/{domain}/subscribers/{subscriber}` | Update a subscriber |
| `delete_subscriber` | DELETE | `/1/newsletters/{domain}/subscribers/{subscriber}` | Delete a subscriber |
| `forget_subscriber` | DELETE | `/1/newsletters/{domain}/subscribers/{subscriber}/forget` | Forget a subscriber (GDPR) |
| `filter_subscribers` | POST | `/1/newsletters/{domain}/subscribers/filter` | Filter subscribers |
| `export_subscribers` | POST | `/1/newsletters/{domain}/subscribers/export` | Export subscribers |
| `import_subscribers` | POST | `/1/newsletters/{domain}/subscribers/import` | Import subscribers |
| `upload_csv` | POST | `/1/newsletters/{domain}/subscribers/import/upload` | Upload CSV file |
| `list_addressbook` | GET | `/1/newsletters/{domain}/subscribers/import/workspace` | List address books |

#### Groups (8)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_groups` | GET | `/1/newsletters/{domain}/groups` | List all groups |
| `create_group` | POST | `/1/newsletters/{domain}/groups` | Create a group |
| `delete_groups_bulk` | DELETE | `/1/newsletters/{domain}/groups` | Bulk delete groups |
| `get_group` | GET | `/1/newsletters/{domain}/groups/{group}` | Fetch a group |
| `update_group` | PUT | `/1/newsletters/{domain}/groups/{group}` | Update a group |
| `delete_group` | DELETE | `/1/newsletters/{domain}/groups/{group}` | Delete a group |
| `list_group_subscribers` | GET | `/1/newsletters/{domain}/groups/{group}/subscribers` | List group subscribers |

#### Segments (6)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_segments` | GET | `/1/newsletters/{domain}/segments` | List all segments |
| `create_segment` | POST | `/1/newsletters/{domain}/segments` | Create a segment |
| `delete_segments_bulk` | DELETE | `/1/newsletters/{domain}/segments` | Bulk delete segments |
| `get_segment` | GET | `/1/newsletters/{domain}/segments/{segment}` | Fetch a segment |
| `update_segment` | PUT | `/1/newsletters/{domain}/segments/{segment}` | Update a segment |
| `delete_segment` | DELETE | `/1/newsletters/{domain}/segments/{segment}` | Delete a segment |

#### Fields (5)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_fields` | GET | `/1/newsletters/{domain}/fields` | List all fields |
| `create_field` | POST | `/1/newsletters/{domain}/fields` | Create a field |
| `delete_fields_bulk` | DELETE | `/1/newsletters/{domain}/fields` | Bulk delete fields |
| `update_field` | PUT | `/1/newsletters/{domain}/fields/{field}` | Update a field |
| `delete_field` | DELETE | `/1/newsletters/{domain}/fields/{field}` | Delete a field |

#### Templates (3)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_templates` | GET | `/1/newsletters/{domain}/templates` | List all templates |
| `get_template_html` | GET | `/1/newsletters/{domain}/templates/{template}/html` | Show template HTML |
| `update_thumbnail` | PUT | `/1/newsletters/{domain}/templates/{template}/update-thumbnails` | Update template thumbnail |

#### Webforms (8)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_webforms` | GET | `/1/newsletters/{domain}/webforms` | List all webforms |
| `create_webform` | POST | `/1/newsletters/{domain}/webforms` | Create a webform |
| `delete_webforms_bulk` | DELETE | `/1/newsletters/{domain}/webforms` | Bulk delete webforms |
| `list_webform_themes` | GET | `/1/newsletters/{domain}/webforms/themes` | List webform themes |
| `get_webform` | GET | `/1/newsletters/{domain}/webforms/{webform}` | Fetch a webform |
| `update_webform` | PUT | `/1/newsletters/{domain}/webforms/{webform}` | Update a webform |
| `delete_webform` | DELETE | `/1/newsletters/{domain}/webforms/{webform}` | Delete a webform |
| `list_webform_fields` | GET | `/1/newsletters/{domain}/webforms/{webform}/fields` | List webform fields |

#### Dashboard & Credits (11)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `get_newsletter_dashboard` | GET | `/1/newsletters/{domain}/dashboard` | Show dashboard |
| `list_dashboard_campaigns` | GET | `/1/newsletters/{domain}/dashboard/campaigns` | Latest campaigns |
| `get_dashboard_subscriber_stats` | GET | `/1/newsletters/{domain}/dashboard/stats/subscribers` | Subscriber stats |
| `get_dashboard_campaign_stats` | GET | `/1/newsletters/{domain}/dashboard/stats/campaigns` | Campaign stats |
| `get_monthly_campaign_stats` | GET | `/1/newsletters/{domain}/dashboard/stats/campaigns/monthly` | Monthly campaign stats |
| `get_newsletter_domain` | GET | `/1/newsletters/{domain}` | Display domain |
| `delete_newsletter_domain` | DELETE | `/1/newsletters/{domain}` | Delete domain |
| `list_credits` | GET | `/1/newsletters/{domain}/credits` | List all credits |
| `get_credits_accounts` | GET | `/1/newsletters/{domain}/credits/accounts` | Account credits |
| `get_credits_details` | GET | `/1/newsletters/{domain}/credits/details` | Credits details |
| `list_credits_offers` | GET | `/1/newsletters/{domain}/credits/packs` | List credit offers |

---

### VOD (15 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_vod_products` | GET | `/2/vod` | List VOD products |
| `get_vod_product` | GET | `/2/vod/{product_id}` | Get a VOD product |
| `list_vod_channels` | GET | `/2/vod/{product_id}/channels` | List channels |
| `get_vod_channel` | GET | `/2/vod/{product_id}/channels/{channel_id}` | Get a channel |
| `list_vod_media` | GET | `/2/vod/{product_id}/media` | List media |
| `get_vod_media` | GET | `/2/vod/{product_id}/media/{media_id}` | Get media |
| `list_vod_encodings` | GET | `/2/vod/{product_id}/encodings` | List encodings |
| `get_vod_encoding` | GET | `/2/vod/{product_id}/encodings/{encoding_id}` | Get an encoding |
| `list_vod_statistics` | GET | `/2/vod/{product_id}/statistics` | List statistics |
| `list_vod_folders` | GET | `/2/vod/{product_id}/folders` | List folders |
| `list_vod_playlists` | GET | `/2/vod/{product_id}/playlists` | List playlists |
| `list_vod_shares` | GET | `/2/vod/{product_id}/shares` | List shares |
| `get_vod_disk_usage` | GET | `/2/vod/{product_id}/disk-usage` | Get disk usage |
| `list_vod_players` | GET | `/2/vod/{product_id}/players` | List players |
| `list_vod_subtitles` | GET | `/2/vod/{product_id}/subtitles` | List subtitles |

For VOD endpoints not covered by dedicated tools (chapters, thumbnails, mixtapes, FTP, ads, etc.), use `infomaniak_api_call`.

---

### Generic (1 tool)

| Tool | Description |
|------|-------------|
| `infomaniak_api_call` | Call any of the 577 Infomaniak API endpoints. Use for endpoints not covered by dedicated tools. |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `method` | string | Yes | HTTP method: `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `path` | string | Yes | API path starting with `/`, e.g. `/2/vod/{product_id}/channels/{channel_id}/chapters` |
| `body` | object | No | Request body (for POST/PUT/PATCH) |
| `params` | object | No | Query parameters |

**Example:**

```json
{
  "method": "GET",
  "path": "/2/vod/123/channels/456/chapters"
}
```

## Integration with OpenCode Skills

| Skill | MCP Tools Used | Benefit |
|-------|---------------|---------|
| `deployment-changelog` | `list_events` or generic `POST /2/events/private` | Replaces `curl` with structured tool calls |
| `release-smoke-test` | `get_public_cloud_status`, `list_events` | Verify cloud status during smoke tests |
| `gitlab-summary` | `list_events` | Check maintenance events for daily summary |

## API Rules

- **Rate limit**: 60 requests per minute (handled automatically by the client)
- **Response format**: `{ result: "success" | "error", data: ..., error: { code, description } }`
- **Pagination**: Supports `page`/`per_page` and `limit`/`skip` on list endpoints
- **Auth**: All endpoints require a Bearer token with appropriate scopes
- **Token creation**: [manager.infomaniak.com](https://manager.infomaniak.com/v3/ng/accounts/token/list)

## Development

```bash
# Install dependencies
cd mcp/infomaniak
npm install

# Build
npm run build

# Type check (no output)
npx tsc --noEmit

# Run manually (stdio transport)
node dist/index.js
```

## Adding New Tools

1. Add the tool definition to the appropriate module file in `src/modules/`
2. Follow the existing pattern: `name`, `description`, `inputSchema` (JSON Schema), `handler` (calls `apiCall`)
3. For new categories, create a new module file and import it in `src/index.ts`
4. Run `npm run build` to compile

## License

This MCP server is part of the opencode-config repository.
