import { readdirSync } from 'node:fs'
import { delimiter, isAbsolute, resolve } from 'node:path'
import { type ToolSet } from 'ai'
import { makeFsTools } from './fsTools.js'
import { workspaceDir } from '../../config/paths.js'
import { env } from '../../config/env.js'
import type { AgentConfig } from '../../agents/types.js'
import type { RunContext, RunLineage } from '../../runtime/context.js'

function scopedJobDirs(root: string, jobRef: string): string[] {
    const match = /^([^#]+)#(\d+)$/.exec(jobRef.trim())
    if (!match) return [root]
    const [, repo, num] = match
    const repoName = repo!.split('/').pop()!
    const repoDir = resolve(root, repoName)
    const prefix = `${num}-`
    try {
        const matches = readdirSync(repoDir, { withFileTypes: true })
            .filter(entry => entry.isDirectory() && (entry.name === num || entry.name.startsWith(prefix)))
            .map(entry => resolve(repoDir, entry.name))
        if (matches.length > 0) return matches
    } catch {
        return [resolve(repoDir, num!)]
    }
    return [resolve(repoDir, num!)]
}

export function fsExtraRoots(config: AgentConfig, lineage?: RunLineage): string[] {
    if (!config.tools.shell) return []
    const roots = (env().RERUN_FS_EXTRA_ROOTS ?? '').split(delimiter).filter(root => isAbsolute(root)).map(root => resolve(root))
    if (!lineage?.jobRef) return roots
    return roots.flatMap(root => scopedJobDirs(root, lineage.jobRef!))
}

export function filesystemTools(ctx: RunContext): ToolSet {
    return makeFsTools({ prefix: 'fs', label: 'coworker workspace', rootDir: workspaceDir(ctx.agent.id), extraRoots: fsExtraRoots(ctx.agent.config, ctx.lineage) })
}
