#!/usr/bin/env npx tsx
import { spawn } from 'child_process'

const market = spawn('npx', ['tsx', 'server/market-api.ts'], { stdio: 'inherit', shell: true })
const vite = spawn('npm', ['run', 'dev'], { stdio: 'inherit', shell: true })

function cleanup() {
  market.kill()
  vite.kill()
  process.exit(0)
}

process.on('SIGINT', cleanup)
process.on('SIGTERM', cleanup)

market.on('exit', code => { if (code) cleanup() })
vite.on('exit', code => { if (code) cleanup() })
