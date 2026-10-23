#!/usr/bin/env node
/**
 * Angular Elements MCP Server — Entry point.
 *
 * Exposes the Infomaniak Angular Elements design system documentation
 * via stdio transport. Reads from GitLab API + Storybook index.json.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import {
  listComponentsTool,
  searchComponentsTool,
  getComponentDocsTool,
  getComponentApiTool,
  getComponentStoriesTool,
  getInstallInfoTool,
  getChangelogTool,
} from "./modules/elements.js";
import { validateStartupConfig } from "./client.js";

// Fail-closed startup: a misconfigured endpoint never reaches the network layer (F-01).
validateStartupConfig();

const allTools = [
  listComponentsTool,
  searchComponentsTool,
  getComponentDocsTool,
  getComponentApiTool,
  getComponentStoriesTool,
  getInstallInfoTool,
  getChangelogTool,
];

const server = new Server(
  { name: "angular-elements-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: allTools.map((t) => ({
    name: t.name,
    description: t.description,
    inputSchema: t.inputSchema,
  })),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const tool = allTools.find((t) => t.name === request.params.name);
  if (!tool) {
    return {
      isError: true,
      content: [{ type: "text", text: `Unknown tool: ${request.params.name}` }],
    };
  }
  try {
    const result = await tool.handler(request.params.arguments || {});
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (e) {
    return {
      isError: true,
      content: [{ type: "text", text: e instanceof Error ? e.message : String(e) }],
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
