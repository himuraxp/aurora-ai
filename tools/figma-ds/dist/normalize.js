/**
 * Normalize raw Figma data to clean JSON structures
 */
/**
 * Normalize capture result to output format
 */
export function normalizeCapture(result) {
    return {
        meta: normalizeMeta(result.meta),
        structure: normalizeStructure(result.structure),
        styles: normalizeStyles(result.styles.styles),
        components: normalizeComponents(result.components),
        variables: normalizeVariables(result.variables)
    };
}
function normalizeMeta(meta) {
    return {
        file_key: meta.file_key,
        file_name: meta.file_name,
        lastModified: meta.lastModified,
        version: meta.version,
        syncedAt: meta.syncedAt,
        contentStatus: meta.contentStatus,
        counts: meta.counts,
        variables: meta.variables
    };
}
function normalizeStructure(structure) {
    function cleanPage(p) {
        const cleaned = {
            name: p.name,
            id: p.id,
            childCount: p.childCount,
            depth: p.depth
        };
        if (p.children && p.children.length > 0) {
            cleaned.children = p.children.map(cleanPage);
        }
        return cleaned;
    }
    return {
        pages: structure.pages.map(cleanPage)
    };
}
function normalizeStyles(styles) {
    return styles.map(s => ({
        key: s.key,
        file_key: s.file_key,
        node_id: s.node_id,
        name: s.name,
        style_type: normalizeStyleType(s.style_type),
        description: s.description,
        // Present only when /nodes was reachable — absent (not null) when gated
        ...(s.resolvedValue !== undefined ? { resolvedValue: s.resolvedValue } : {})
    }));
}
function normalizeStyleType(type) {
    const typeMap = {
        FILL: 'fill',
        TEXT: 'text',
        EFFECT: 'effect',
        GRID: 'grid'
    };
    return typeMap[type] || type.toLowerCase();
}
function normalizeComponents(components) {
    return {
        components: components.components.map((c) => ({
            key: c.key,
            node_id: c.node_id,
            name: c.name,
            description: c.description
        })),
        componentSets: components.componentSets.map((s) => ({
            key: s.key,
            node_id: s.node_id,
            name: s.name,
            description: s.description
        })),
        componentProperties: components.componentProperties.map((p) => ({
            node_id: p.node_id,
            name: p.name,
            type: p.type,
            defaultValue: p.defaultValue
        })),
        componentPropertiesStatus: components.componentPropertiesStatus
    };
}
function normalizeVariables(variables) {
    return {
        status: variables.status,
        reason: variables.reason,
        count: variables.variables?.length
    };
}
export function computeDiff(oldData, newData, options = {}) {
    const diff = {
        styles: { added: 0, removed: 0, changed: 0 },
        components: { added: 0, removed: 0, changed: 0 },
        componentSets: { added: 0, removed: 0, changed: 0 },
        pages: { added: 0, removed: 0, changed: 0 },
        hasChanges: false
    };
    // Styles diff
    if (oldData.styles && newData.styles) {
        const oldStyleIds = new Set(oldData.styles.map((s) => s.node_id));
        const newStyleIds = new Set(newData.styles.map((s) => s.node_id));
        diff.styles.added = newData.styles.filter((s) => !oldStyleIds.has(s.node_id)).length;
        diff.styles.removed = oldData.styles.filter((s) => !newStyleIds.has(s.node_id)).length;
        diff.styles.changed = newData.styles.filter((s) => {
            const old = oldData.styles.find((os) => os.node_id === s.node_id);
            return old && (old.name !== s.name || old.style_type !== s.style_type);
        }).length;
    }
    // Components diff
    if (oldData.components && newData.components) {
        const oldCompIds = new Set(oldData.components.map((c) => c.key));
        const newCompIds = new Set(newData.components.map((c) => c.key));
        diff.components.added = newData.components.filter((c) => !oldCompIds.has(c.key)).length;
        diff.components.removed = oldData.components.filter((c) => !newCompIds.has(c.key)).length;
        diff.components.changed = newData.components.filter((c) => {
            const old = oldData.components.find((oc) => oc.key === c.key);
            return old && old.description !== c.description;
        }).length;
    }
    // ComponentSets diff
    if (oldData.componentSets && newData.componentSets) {
        const oldSetIds = new Set(oldData.componentSets.map((s) => s.key));
        const newSetIds = new Set(newData.componentSets.map((s) => s.key));
        diff.componentSets.added = newData.componentSets.filter((s) => !oldSetIds.has(s.key)).length;
        diff.componentSets.removed = oldData.componentSets.filter((s) => !newSetIds.has(s.key)).length;
        diff.componentSets.changed = newData.componentSets.filter((s) => {
            const old = oldData.componentSets.find((os) => os.key === s.key);
            return old && old.description !== s.description;
        }).length;
    }
    // Pages diff — ONLY when both sides captured the page tree.
    // A gated sync produces pages: [] which would fake "removed" then "added" entries.
    if (oldData.pages && newData.pages && !options.newGated) {
        const oldPageIds = new Set(oldData.pages.map((p) => p.id));
        const newPageIds = new Set(newData.pages.map((p) => p.id));
        diff.pages.added = newData.pages.filter((p) => !oldPageIds.has(p.id)).length;
        diff.pages.removed = oldData.pages.filter((p) => !newPageIds.has(p.id)).length;
    }
    diff.hasChanges =
        diff.styles.added > 0 || diff.styles.removed > 0 || diff.styles.changed > 0 ||
            diff.components.added > 0 || diff.components.removed > 0 || diff.components.changed > 0 ||
            diff.componentSets.added > 0 || diff.componentSets.removed > 0 || diff.componentSets.changed > 0 ||
            diff.pages.added > 0 || diff.pages.removed > 0 ||
            // Availability/variables changes are meaningful too (quota transitions, token rescope)
            oldData.meta?.variables?.status !== newData.meta?.variables?.status ||
            oldData.meta?.contentStatus !== newData.meta?.contentStatus;
    return diff;
}
/**
 * Generate CHANGELOG entry from diff
 */
export function generateChangelogEntry(diff, meta) {
    const date = new Date(meta.syncedAt).toISOString().split('T')[0];
    const lines = [];
    lines.push(`## Sync du ${date}`);
    lines.push('');
    lines.push(`**Fichier**: ${meta.file_name} (${meta.file_key})`);
    lines.push(`**Dernière modification**: ${meta.lastModified}`);
    lines.push(`**Variables**: ${meta.variables.status === 'available' ? '✓' : '✗'} (${meta.variables.reason || 'N/A'})`);
    if (meta.contentStatus === 'gated') {
        lines.push('');
        lines.push('> ⚠️ Snapshot dégradé (quota Figma) : structure des pages et valeurs résolues non comparées.');
    }
    lines.push('');
    if (!diff.hasChanges) {
        lines.push('Aucun changement structurel détecté.');
        lines.push('');
        return lines.join('\n');
    }
    lines.push('### Changelog');
    lines.push('');
    // Styles
    if (diff.styles.added > 0 || diff.styles.removed > 0 || diff.styles.changed > 0) {
        lines.push(`#### Styles (${diff.styles.added + diff.styles.removed + diff.styles.changed} changements)`);
        lines.push('');
        if (diff.styles.added > 0)
            lines.push(`- ✚ ${diff.styles.added} ajouté(s)`);
        if (diff.styles.removed > 0)
            lines.push(`- ✖ ${diff.styles.removed} supprimé(s)`);
        if (diff.styles.changed > 0)
            lines.push(`- ~ ${diff.styles.changed} modifié(s)`);
        lines.push('');
    }
    // Components
    if (diff.components.added > 0 || diff.components.removed > 0 || diff.components.changed > 0) {
        lines.push(`#### Composants (${diff.components.added + diff.components.removed + diff.components.changed} changements)`);
        lines.push('');
        if (diff.components.added > 0)
            lines.push(`- ✚ ${diff.components.added} ajouté(s)`);
        if (diff.components.removed > 0)
            lines.push(`- ✖ ${diff.components.removed} supprimé(s)`);
        if (diff.components.changed > 0)
            lines.push(`- ~ ${diff.components.changed} modifié(s)`);
        lines.push('');
    }
    // ComponentSets
    if (diff.componentSets.added > 0 || diff.componentSets.removed > 0 || diff.componentSets.changed > 0) {
        lines.push(`#### Variant Sets (${diff.componentSets.added + diff.componentSets.removed + diff.componentSets.changed} changements)`);
        lines.push('');
        if (diff.componentSets.added > 0)
            lines.push(`- ✚ ${diff.componentSets.added} ajouté(s)`);
        if (diff.componentSets.removed > 0)
            lines.push(`- ✖ ${diff.componentSets.removed} supprimé(s)`);
        if (diff.componentSets.changed > 0)
            lines.push(`- ~ ${diff.componentSets.changed} modifié(s)`);
        lines.push('');
    }
    // Pages
    if (diff.pages.added > 0 || diff.pages.removed > 0) {
        lines.push(`#### Pages (${diff.pages.added + diff.pages.removed} changements)`);
        lines.push('');
        if (diff.pages.added > 0)
            lines.push(`- ✚ ${diff.pages.added} ajouté(s)`);
        if (diff.pages.removed > 0)
            lines.push(`- ✖ ${diff.pages.removed} supprimé(s)`);
        lines.push('');
    }
    lines.push('---');
    lines.push('');
    return lines.join('\n');
}
