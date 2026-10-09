/**
 * Capture metadata, structure, styles, components from Figma
 *
 * Resilience strategy: Figma gates the *content* endpoints (/files/{key}, /nodes)
 * behind a plan-level API quota (429 + long Retry-After) while the *dedicated*
 * endpoints (/files/{key}/styles, /components, /component_sets, /versions) stay
 * available. Every gated call is optional and degrades gracefully:
 *   - structure: unavailable when gated
 *   - style resolved values / component properties: omitted when gated
 *   - lastModified: falls back to the latest file version date via /versions
 */
import { FigmaQuotaError, HttpError } from './figma-client.js';
import { DEFAULT_FILE_NAME } from './config.js';
export async function captureMeta(client, fileKey) {
    // depth=2 gives pages + their direct children in a single request (reused by captureStructure).
    // May be gated by Figma's plan quota — fall back to /versions for lastModified.
    try {
        const fileData = await client.getFile(fileKey, 2);
        const meta = {
            file_key: fileKey,
            file_name: fileData.name,
            lastModified: fileData.lastModified,
            version: fileData.version,
            syncedAt: new Date().toISOString(),
            contentStatus: 'available',
            counts: {
                pages: fileData.document?.children?.length || 0,
                styles: 0,
                components: 0,
                componentSets: 0
            },
            variables: { status: 'unavailable', reason: 'not yet captured' }
        };
        return { meta, fileData };
    }
    catch (error) {
        if (!(error instanceof FigmaQuotaError))
            throw error;
        // Gated fallback: dedicated endpoints still work, use latest version date
        console.error('File content gated by Figma quota — using /versions for lastModified');
        const versions = await client.getVersions(fileKey);
        const last = versions.versions?.[0]?.created_at || new Date(0).toISOString();
        const meta = {
            file_key: fileKey,
            file_name: DEFAULT_FILE_NAME,
            lastModified: last,
            version: versions.versions?.[0]?.id || 'unknown',
            syncedAt: new Date().toISOString(),
            contentStatus: 'gated',
            counts: { pages: 0, styles: 0, components: 0, componentSets: 0 },
            variables: { status: 'unavailable', reason: 'not yet captured' }
        };
        return { meta, fileData: null };
    }
}
export async function captureStructure(client, fileKey, fileData) {
    if (!fileData) {
        return {
            status: 'unavailable',
            reason: 'File content gated by Figma API quota (/files endpoint returns 429 with long Retry-After)',
            pages: []
        };
    }
    function buildPageStructure(nodes, depth = 0) {
        return nodes.map(node => ({
            name: node.name,
            id: node.id,
            // depth=2 truncates children: only report a count when Figma actually sent them.
            childCount: node.children ? node.children.length : undefined,
            depth,
            children: node.children ? buildPageStructure(node.children, depth + 1) : undefined
        }));
    }
    return {
        status: 'available',
        pages: buildPageStructure(fileData.document?.children || [], 0)
    };
}
export async function captureStyles(client, fileKey) {
    const stylesMeta = await client.getStyles(fileKey);
    const styles = stylesMeta.meta?.styles || [];
    // Resolve style values via batched node fetch — /nodes may be gated by quota.
    // No slice: 118 styles = 3 batchs de 50, budget raisonnable.
    const styleNodeIds = styles.map((s) => s.node_id);
    let resolvedValues = {};
    if (styleNodeIds.length > 0) {
        console.log(`Resolving ${styleNodeIds.length} style values...`);
        try {
            resolvedValues = await client.batchGetNodes(fileKey, styleNodeIds, 1);
        }
        catch (error) {
            if (error instanceof FigmaQuotaError) {
                console.error('Node content gated by quota — capturing styles metadata without resolved values');
            }
            else {
                throw error;
            }
        }
    }
    const normalizedStyles = styles.map((s) => {
        const resolved = resolvedValues[s.node_id];
        return {
            key: s.key,
            file_key: s.file_key,
            node_id: s.node_id,
            name: s.name,
            style_type: s.style_type,
            description: s.description,
            resolvedValue: resolved?.document
        };
    });
    return {
        styles: { styles: normalizedStyles },
        stylesMeta,
        rawNodes: resolvedValues
    };
}
export async function captureComponents(client, fileKey) {
    const componentsMeta = await client.getComponents(fileKey);
    const componentSetsMeta = await client.getComponentSets(fileKey);
    // /components and /component_sets return { meta: { components: [...] | {...} } }
    // The payload is a list (not a map) in practice; support both shapes defensively.
    const toList = (payload) => {
        if (Array.isArray(payload))
            return payload;
        return Object.entries(payload || {}).map(([key, value]) => ({ key, ...value }));
    };
    const components = toList(componentsMeta.meta?.components).map((comp) => ({
        key: comp.key,
        node_id: comp.node_id,
        name: comp.name,
        description: comp.description
    }));
    const componentSets = toList(componentSetsMeta.meta?.component_sets).map((set) => ({
        key: set.key,
        node_id: set.node_id,
        name: set.name,
        description: set.description
    }));
    // Fetch component properties via node fetch (optional, may be expensive AND gated).
    // Budget guard decided on the full set count, capped at 50 ids per run (1 batch).
    const PROPERTIES_MAX_SETS = 60;
    const BATCH_CAP = 50;
    const totalSets = componentSets.length;
    let componentProperties = [];
    let componentPropertiesStatus = 'skipped';
    let rawNodes = {};
    if (totalSets === 0) {
        // nothing to resolve
    }
    else if (totalSets <= PROPERTIES_MAX_SETS) {
        const setNodeIds = componentSets.map(s => s.node_id).slice(0, BATCH_CAP);
        console.log(`Fetching component set properties: ${Math.min(totalSets, BATCH_CAP)} sets...`);
        try {
            rawNodes = await client.batchGetNodes(fileKey, setNodeIds, 1);
            componentProperties = Object.values(rawNodes).flatMap((node) => {
                if (!node?.document?.componentPropertyDefinitions)
                    return [];
                return Object.entries(node.document.componentPropertyDefinitions).map(([name, def]) => ({
                    node_id: node.id,
                    name,
                    type: def.type,
                    defaultValue: def.default
                }));
            });
            componentPropertiesStatus = totalSets > BATCH_CAP ? 'partial' : 'complete';
        }
        catch (error) {
            if (error instanceof FigmaQuotaError) {
                console.error('Node content gated by quota — capturing component sets metadata without properties');
                componentPropertiesStatus = 'skipped';
            }
            else {
                throw error;
            }
        }
    }
    else {
        console.log(`Skipping component properties fetch (${totalSets} sets > ${PROPERTIES_MAX_SETS} budget)`);
    }
    return {
        components: {
            components,
            componentSets,
            componentProperties,
            componentPropertiesStatus
        },
        componentsMeta,
        componentSetsMeta,
        rawNodes
    };
}
export async function captureVariables(client, fileKey) {
    try {
        const variablesData = await client.getVariablesLocal(fileKey);
        const vars = variablesData?.variables || [];
        return {
            status: 'available',
            variables: vars
        };
    }
    catch (error) {
        if (error instanceof HttpError && error.status === 403) {
            return {
                status: 'unavailable',
                reason: 'Token missing variables scope'
            };
        }
        return {
            status: 'unavailable',
            reason: error.message || 'Unknown error'
        };
    }
}
export async function captureAll(client, fileKey) {
    console.log('Capturing meta...');
    const { meta, fileData } = await captureMeta(client, fileKey);
    console.log('Capturing structure...');
    const structure = await captureStructure(client, fileKey, fileData);
    console.log('Capturing styles...');
    const { styles, stylesMeta, rawNodes: styleNodes } = await captureStyles(client, fileKey);
    console.log('Capturing components...');
    const { components, componentsMeta, componentSetsMeta, rawNodes: componentNodes } = await captureComponents(client, fileKey);
    console.log('Capturing variables...');
    const variables = await captureVariables(client, fileKey);
    // Update counts
    meta.counts.styles = styles.styles.length;
    meta.counts.components = components.components.length;
    meta.counts.componentSets = components.componentSets.length;
    // Update variables status in meta
    meta.variables = variables;
    return {
        meta,
        structure,
        styles,
        components,
        variables,
        raw: {
            fileData,
            stylesMeta,
            componentsMeta,
            componentSetsMeta,
            nodesBatch: { ...styleNodes, ...componentNodes },
            variablesData: variables.status === 'available' ? variables.variables : undefined
        }
    };
}
