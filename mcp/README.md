# mcp/

> **Language note:** MCP servers are Node.js code (language-neutral); this documentation and code comments may be partially in French — the maintainer's working language. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

MCP (Model Context Protocol) servers for OpenCode. Each server exposes specific tools via stdio transport.

## Servers

| Server | Description | README |
|--------|-------------|--------|
| `infomaniak/` | Infomaniak API — radio, VOD, newsletter, DNS, events, AI, accounts | [README](infomaniak/README.md) |
| `angular-elements/` | Angular Elements design system — components, API, stories, install info | [README](angular-elements/README.md) |

## Configuration

MCP servers are declared in `config/opencode.json`:

```json
{
  "mcp": {
    "infomaniak": {
      "type": "local",
      "command": ["node", "{env:HOME}/.config/opencode-config/mcp/infomaniak/dist/index.js"],
      "enabled": true,
      "timeout": 30000,
      "env": {
        "INFOMANIAK_API_TOKEN": "{env:INFOMANIAK_API_TOKEN}"
      }
    },
    "angular-elements": {
      "type": "local",
      "command": ["node", "{env:HOME}/.config/opencode-config/mcp/angular-elements/dist/index.js"],
      "enabled": true,
      "timeout": 30000,
      "env": {
        "GITLAB_TOKEN": "{env:GITLAB_TOKEN}"
      }
    }
  }
}
```

## Built-in MCP servers (npx)

In addition to the local servers above, the config includes three servers auto-installed via npx:

| Server | Command | Description |
|--------|---------|-------------|
| `context7` | `npx -y @upstash/context7-mcp` | Up-to-date library and framework documentation |
| `chrome-devtools` | `npx -y chrome-devtools-mcp@latest --headless --isolated` | Browser debugging, screenshots, performance traces |
| `ios-simulator` | `npx -y ios-simulator-mcp` | iOS simulator control (screenshots, UI, tap) |

## Development

```bash
# Build a server
cd mcp/<server-name>
npm install
npm run build

# Dev mode (watch)
npm run dev

# Run
npm start
```

## Adding an MCP server

1. Create a `mcp/<server-name>/` folder
2. Initialize a Node.js project with `@modelcontextprotocol/sdk`
3. Implement the tools (see `angular-elements/` as an example)
4. Add the entry in `config/opencode.json` → `mcp.<server-name>`
5. Run `npm run update` (or `./scripts/install.sh`) to deploy
