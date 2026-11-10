#!/usr/bin/env npx tsx
/**
 * 轻量市场分析读 API — SQLite 样本数据
 */

import path from 'path'
import Database from 'better-sqlite3'
import Fastify from 'fastify'
import cors from '@fastify/cors'
import { REGION_CODE_TO_NAME } from '../src/features/market-analysis/lib/marketRegions.ts'

const PORT = parseInt(process.env.MARKET_API_PORT || '8010', 10)
const DB_PATH = process.env.PROCUREMENT_DB || path.join(process.cwd(), 'data/procurement.sqlite')

const db = new Database(DB_PATH, { readonly: true })

const ANNOUNCEMENT_FROM = `
  FROM cjgg cjgg
  LEFT JOIN (
    SELECT GGWID AS link_wid, SUM(CJJE) AS total_amount, MIN(NULLIF(TRIM(region), '')) AS region_name
    FROM cjs WHERE GGWID IS NOT NULL AND GGWID <> '' GROUP BY GGWID
  ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = cjgg.WID
  LEFT JOIN (
    SELECT WID AS link_wid, SUM(CJJE) AS total_amount, MIN(NULLIF(TRIM(region), '')) AS region_name
    FROM cjs WHERE WID IS NOT NULL AND WID <> '' GROUP BY WID
  ) cjs_by_wid ON cjs_by_wid.link_wid = cjgg.WID
`
const AMOUNT_SQL = 'COALESCE(cjs_by_ggwid.total_amount, cjs_by_wid.total_amount, 0)'
const REGION_SQL = "COALESCE(cjs_by_ggwid.region_name, cjs_by_wid.region_name, cjgg.CGRDZ, '')"

function buildKeywordFilter(search: string): { clause: string; params: string[] } {
  if (!search.trim()) return { clause: '', params: [] }
  const keywords = search.trim().split(/\s+/).slice(0, 10)
  const parts = keywords.map(() => '(cjgg.GGBT LIKE ? OR cjgg.XMMC LIKE ? OR cjgg.CGRMC LIKE ? OR cjgg.XMBH LIKE ?)')
  const params: string[] = []
  for (const kw of keywords) {
    const p = `%${kw}%`
    params.push(p, p, p, p)
  }
  return { clause: ` AND (${parts.join(' OR ')})`, params }
}

function buildTimeFilter(time: string): { clause: string; params: string[] } {
  if (!time) return { clause: '', params: [] }
  const today = new Date().toISOString().slice(0, 10)
  const map: Record<string, number> = { today: 0, month: 30, three_months: 90, six_months: 180, year: 365 }
  const days = map[time]
  if (days === undefined) return { clause: '', params: [] }
  if (days === 0) return { clause: ' AND date(cjgg.GGFBRQ) = date(?)', params: [today] }
  const d = new Date()
  d.setDate(d.getDate() - days)
  return { clause: ' AND date(cjgg.GGFBRQ) >= date(?)', params: [d.toISOString().slice(0, 10)] }
}

function buildAmountFilter(amount: string): { clause: string; params: unknown[] } {
  switch (amount) {
    case 'below_1': return { clause: ` AND ${AMOUNT_SQL} < 10000`, params: [] }
    case '1_10': return { clause: ` AND ${AMOUNT_SQL} >= 10000 AND ${AMOUNT_SQL} < 100000`, params: [] }
    case '10_100': return { clause: ` AND ${AMOUNT_SQL} >= 100000 AND ${AMOUNT_SQL} < 1000000`, params: [] }
    case '100_500': return { clause: ` AND ${AMOUNT_SQL} >= 1000000 AND ${AMOUNT_SQL} < 5000000`, params: [] }
    case 'above_500': return { clause: ` AND ${AMOUNT_SQL} >= 5000000`, params: [] }
    default: return { clause: '', params: [] }
  }
}

function buildRegionFilter(region: string): { clause: string; params: string[] } {
  if (!region || region === 'all') return { clause: '', params: [] }
  const name = REGION_CODE_TO_NAME[region] || region
  return { clause: ` AND ${REGION_SQL} LIKE ?`, params: [`%${name}%`] }
}

async function start() {
  const app = Fastify({ logger: false })
  await app.register(cors, { origin: true })

  app.get('/health', async () => ({ ok: true, db: DB_PATH }))

  app.get('/announcements', async (req) => {
    const q = req.query as Record<string, string>
    const page = Math.max(1, parseInt(q.page || '1', 10))
    const perPage = Math.min(50, parseInt(q.per_page || '10', 10))
    const offset = (page - 1) * perPage

    const kw = buildKeywordFilter(q.search || '')
    const time = buildTimeFilter(q.time || '')
    const amount = buildAmountFilter(q.amount || '')
    const region = buildRegionFilter(q.region || '')
    const where = `WHERE 1=1${kw.clause}${time.clause}${amount.clause}${region.clause}`
    const params = [...kw.params, ...time.params, ...amount.params, ...region.params]

    const countRow = db.prepare(`
      SELECT COUNT(DISTINCT cjgg.WID) AS cnt
      ${ANNOUNCEMENT_FROM}
      ${where}
    `).get(...params) as { cnt: number }

    const rows = db.prepare(`
      SELECT DISTINCT
        cjgg.WID AS wid, cjgg.GGBT AS title, cjgg.XMMC AS project_name, cjgg.XMBH AS project_number,
        cjgg.CGRMC AS purchaser, cjgg.GGFBRQ AS publish_date, cjgg.GGURL AS url,
        ${AMOUNT_SQL} AS amount, ${REGION_SQL} AS region
      ${ANNOUNCEMENT_FROM}
      ${where}
      ORDER BY cjgg.GGFBRQ DESC, cjgg.CJSJ DESC
      LIMIT ? OFFSET ?
    `).all(...params, perPage, offset)

    return { items: rows, total: countRow?.cnt ?? 0, page, per_page: perPage }
  })

  app.get('/announcements/suggest', async (req) => {
    const q = req.query as { q?: string }
    const prefix = (q.q || '').trim()
    if (!prefix) return { suggestions: [] }
    const rows = db.prepare(`
      SELECT GGBT AS title, COUNT(*) AS cnt FROM cjgg
      WHERE GGBT LIKE ? GROUP BY GGBT ORDER BY cnt DESC LIMIT 8
    `).all(`%${prefix}%`) as { title: string }[]
    return { suggestions: rows.map(r => r.title) }
  })

  app.get('/announcements/:wid', async (req, reply) => {
    const { wid } = req.params as { wid: string }
    const row = db.prepare('SELECT * FROM cjgg WHERE WID = ?').get(wid)
    if (!row) return reply.code(404).send({ error: 'Not found' })
    const transactions = db.prepare(
      'SELECT * FROM cjs WHERE GGWID = ? OR WID = ? ORDER BY CJJE DESC',
    ).all(wid, wid)
    return { announcement: row, transactions }
  })

  app.get('/stats/cards', async (req) => {
    const q = req.query as { keywords?: string }
    const kw = buildKeywordFilter(q.keywords || '')
    const where = `WHERE 1=1${kw.clause}`
    const params = kw.params
    const stats = db.prepare(`
      SELECT
        COUNT(DISTINCT cjgg.WID) AS announcement_count,
        COUNT(DISTINCT cjgg.CGRMC) AS buyer_count,
        COUNT(DISTINCT ${REGION_SQL}) AS region_count,
        COALESCE(SUM(${AMOUNT_SQL}), 0) AS total_amount
      ${ANNOUNCEMENT_FROM}
      ${where}
    `).get(...params)
    return stats
  })

  app.get('/stats/regions', async (req) => {
    const q = req.query as { keywords?: string }
    const kw = buildKeywordFilter(q.keywords || '')
    const where = `WHERE 1=1${kw.clause}`
    const rows = db.prepare(`
      SELECT ${REGION_SQL} AS region, COUNT(DISTINCT cjgg.WID) AS count, SUM(${AMOUNT_SQL}) AS amount
      ${ANNOUNCEMENT_FROM}
      ${where}
      GROUP BY region ORDER BY amount DESC LIMIT 20
    `).all(...kw.params)
    return { regions: rows }
  })

  app.get('/stats/top-buyers', async (req) => {
    const q = req.query as { keywords?: string; limit?: string }
    const limit = Math.min(20, parseInt(q.limit || '10', 10))
    const kw = buildKeywordFilter(q.keywords || '')
    const where = `WHERE cjgg.CGRMC IS NOT NULL AND TRIM(cjgg.CGRMC) <> ''${kw.clause}`
    const rows = db.prepare(`
      SELECT cjgg.CGRMC AS buyer, COUNT(DISTINCT cjgg.WID) AS project_count, SUM(${AMOUNT_SQL}) AS total_amount
      ${ANNOUNCEMENT_FROM}
      ${where}
      GROUP BY cjgg.CGRMC ORDER BY total_amount DESC LIMIT ?
    `).all(...kw.params, limit)
    return { buyers: rows }
  })

  app.get('/stats/by-keywords', async (req) => {
    const q = req.query as { keywords?: string; limit?: string }
    const limit = Math.min(100, parseInt(q.limit || '50', 10))
    const kw = buildKeywordFilter(q.keywords || '')
    const where = `WHERE 1=1${kw.clause}`
    const rows = db.prepare(`
      SELECT cjgg.WID AS wid, cjgg.GGBT AS title, cjgg.CGRMC AS purchaser,
        cjgg.GGFBRQ AS publish_date, ${AMOUNT_SQL} AS amount
      ${ANNOUNCEMENT_FROM}
      ${where}
      ORDER BY cjgg.GGFBRQ DESC LIMIT ?
    `).all(...kw.params, limit)
    return { items: rows }
  })

  await app.listen({ port: PORT, host: '127.0.0.1' })
  console.log(`Market API listening on http://127.0.0.1:${PORT}`)
}

start().catch(err => {
  console.error(err)
  process.exit(1)
})
