#!/usr/bin/env npx tsx
/**
 * 从 MySQL INSERT dump 导入 SQLite 样本库
 * Usage: npx tsx scripts/import-procurement-sqlite.ts [--limit 1000] [--cjgg path] [--cjs path]
 *   --limit 0  全量导入（约 1.7 万公告，耗时数分钟）
 */

import fs from 'fs'
import readline from 'readline'
import path from 'path'
import Database from 'better-sqlite3'

const DEFAULT_CJGG = '/Users/holish/Desktop/标书公告和采购代码/zc_wlsjcj_cjgg.sql'
const DEFAULT_CJS = '/Users/holish/Desktop/标书公告和采购代码/zc_wlsjcj_cjs.sql'
const OUT_PATH = path.join(process.cwd(), 'data/procurement.sqlite')

function argValue(flag: string): string | undefined {
  const idx = process.argv.indexOf(flag)
  return idx >= 0 ? process.argv[idx + 1] : undefined
}

export function parseArgs() {
  const limitRaw = argValue('--limit')
  const limit = limitRaw !== undefined ? parseInt(limitRaw, 10) : 1000
  const cjgg = argValue('--cjgg') || process.env.PROCUREMENT_CJGG || DEFAULT_CJGG
  const cjs = argValue('--cjs') || process.env.PROCUREMENT_CJS || DEFAULT_CJS
  return {
    limit: Number.isFinite(limit) ? limit : 1000,
    cjgg,
    cjs,
  }
}

/** 解析单行 INSERT INTO `table` (`col1`,...) VALUES (...); */
export function parseInsertLine(line: string): { table: string; columns: string[]; values: unknown[] } | null {
  const m = line.match(/^INSERT INTO `(\w+)` \(([^)]+)\) VALUES \((.+)\);?\s*$/)
  if (!m) return null
  const table = m[1]
  const columns = m[2].split(',').map(c => c.trim().replace(/`/g, ''))
  const values = parseSqlValues(m[3])
  if (values.length !== columns.length) return null
  return { table, columns, values }
}

export function parseSqlValues(raw: string): unknown[] {
  const values: unknown[] = []
  let i = 0
  while (i < raw.length) {
    while (i < raw.length && (raw[i] === ' ' || raw[i] === ',')) i++
    if (i >= raw.length) break
    if (raw[i] === "'") {
      i++
      let s = ''
      while (i < raw.length) {
        if (raw[i] === "'" && raw[i + 1] === "'") { s += "'"; i += 2 }
        else if (raw[i] === "'") { i++; break }
        else { s += raw[i]; i++ }
      }
      values.push(s)
    } else if (raw.slice(i, i + 4) === 'NULL') {
      values.push(null)
      i += 4
    } else {
      let num = ''
      while (i < raw.length && raw[i] !== ',') { num += raw[i]; i++ }
      const n = parseFloat(num.trim())
      values.push(Number.isNaN(n) ? num.trim() : n)
    }
  }
  return values
}

function rowFromParsed(parsed: { columns: string[]; values: unknown[] }): Record<string, unknown> {
  const row: Record<string, unknown> = {}
  parsed.columns.forEach((col, idx) => { row[col] = parsed.values[idx] })
  return row
}

/** 流式读取 INSERT 行，limit=0 表示不限制 */
async function readInsertRowsStream(
  filePath: string,
  tableName: string,
  maxRows: number,
  filter?: (row: Record<string, unknown>) => boolean,
): Promise<Record<string, unknown>[]> {
  if (!fs.existsSync(filePath)) {
    console.warn(`File not found: ${filePath}`)
    return []
  }
  const rows: Record<string, unknown>[] = []
  const rl = readline.createInterface({
    input: fs.createReadStream(filePath, { encoding: 'utf-8' }),
    crlfDelay: Infinity,
  })
  for await (const line of rl) {
    if (!line.startsWith('INSERT INTO')) continue
    const parsed = parseInsertLine(line.trim())
    if (!parsed || parsed.table !== tableName) continue
    const row = rowFromParsed(parsed)
    if (filter && !filter(row)) continue
    rows.push(row)
    if (maxRows > 0 && rows.length >= maxRows) break
  }
  return rows
}

async function main() {
  const { limit, cjgg, cjs } = parseArgs()
  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true })
  if (fs.existsSync(OUT_PATH)) fs.unlinkSync(OUT_PATH)

  const limitLabel = limit === 0 ? 'all' : String(limit)
  console.log(`Reading up to ${limitLabel} cjgg rows from ${cjgg}...`)
  const cjggRows = await readInsertRowsStream(cjgg, 'zc_wlsjcj_cjgg', limit)
  const widSet = new Set(cjggRows.map(r => String(r.WID)))

  console.log(`Reading cjs rows linked to ${widSet.size} announcements from ${cjs}...`)
  const cjsRows = await readInsertRowsStream(
    cjs,
    'zc_wlsjcj_cjs',
    0,
    row => widSet.has(String(row.GGWID)) || widSet.has(String(row.WID)),
  )

  const db = new Database(OUT_PATH)
  db.exec(`
    CREATE TABLE cjgg (
      WID TEXT PRIMARY KEY,
      WZWID TEXT, CJSJ TEXT, GGNY TEXT, GGFBRQ TEXT, GGBT TEXT, GGLY TEXT,
      GGURL TEXT, XMBH TEXT, XMMC TEXT, BDXX TEXT, PSZH TEXT,
      CGRHY TEXT, CGRSF TEXT, CGRCS TEXT, CGRMC TEXT, CGRDZ TEXT,
      CGRLXFS TEXT, CGRXMLXR TEXT, CGRXMLXDH TEXT,
      CGDLJGMC TEXT, CGDLJGLXR TEXT, CGDLJGLXDH TEXT, CGDLJGDZ TEXT, CGDLJGYX TEXT,
      BZ TEXT, SFYXZFJ TEXT
    );
    CREATE TABLE cjs (
      WID TEXT PRIMARY KEY,
      GGWID TEXT, BJMC TEXT, GYSMC TEXT, GYSDZ TEXT,
      CJJE REAL, CJJESM TEXT, BZ TEXT, region TEXT
    );
    CREATE INDEX idx_cjgg_ggfbrq ON cjgg(GGFBRQ);
    CREATE INDEX idx_cjgg_ggbt ON cjgg(GGBT);
    CREATE INDEX idx_cjgg_cgrmc ON cjgg(CGRMC);
    CREATE INDEX idx_cjs_ggwid ON cjs(GGWID);
  `)

  const insertCjgg = db.prepare(`
    INSERT OR REPLACE INTO cjgg VALUES (
      @WID,@WZWID,@CJSJ,@GGNY,@GGFBRQ,@GGBT,@GGLY,@GGURL,@XMBH,@XMMC,@BDXX,@PSZH,
      @CGRHY,@CGRSF,@CGRCS,@CGRMC,@CGRDZ,@CGRLXFS,@CGRXMLXR,@CGRXMLXDH,
      @CGDLJGMC,@CGDLJGLXR,@CGDLJGLXDH,@CGDLJGDZ,@CGDLJGYX,@BZ,@SFYXZFJ
    )
  `)
  const insertCjs = db.prepare(`
    INSERT OR REPLACE INTO cjs VALUES (@WID,@GGWID,@BJMC,@GYSMC,@GYSDZ,@CJJE,@CJJESM,@BZ,@region)
  `)

  const insertMany = db.transaction((rows: Record<string, unknown>[]) => {
    for (const row of rows) insertCjgg.run(row)
  })
  insertMany(cjggRows)

  const insertCjsMany = db.transaction((rows: Record<string, unknown>[]) => {
    for (const row of rows) insertCjs.run(row)
  })
  insertCjsMany(cjsRows)

  db.close()
  console.log(`Done: ${cjggRows.length} announcements, ${cjsRows.length} transactions → ${OUT_PATH}`)
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
