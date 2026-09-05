#!/usr/bin/env node
import fs from 'node:fs/promises'

const specPath = process.argv[2]
if (!specPath) {
  console.error('Usage: node cdp-runner.mjs <operations.json>')
  process.exit(2)
}

const port = Number(process.env.CDP_PORT || '9222')
const spec = JSON.parse(await fs.readFile(specPath, 'utf8'))
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
const target = targets.find((item) => {
  if (item.type !== 'page') return false
  if (spec.targetUrl && item.url !== spec.targetUrl) return false
  if (spec.targetTitleIncludes && !String(item.title).includes(spec.targetTitleIncludes)) return false
  return true
})
if (!target) throw new Error('No matching CDP page target')

const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true })
  ws.addEventListener('error', reject, { once: true })
})

let nextId = 1
const pending = new Map()
ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (!message.id || !pending.has(message.id)) return
  const { resolve, reject } = pending.get(message.id)
  pending.delete(message.id)
  if (message.error) reject(new Error(JSON.stringify(message.error)))
  else resolve(message.result)
})

function call(method, params = {}) {
  const id = nextId++
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

async function evaluate(expression) {
  const response = await call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  })
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text || 'Runtime.evaluate failed')
  }
  return response.result?.value
}

async function pointFor(op) {
  const expression = op.rectExpression || `(() => {
    const el = document.querySelector(${JSON.stringify(op.selector)})
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { x: r.x, y: r.y, width: r.width, height: r.height }
  })()`
  const rect = await evaluate(expression)
  if (!rect) throw new Error(`No rect for ${op.name || op.selector || 'operation'}`)
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, rect }
}

await call('Runtime.enable')
await call('Page.enable')
const results = []

for (const op of spec.operations || []) {
  if (op.type === 'eval') {
    results.push({ type: op.type, name: op.name, value: await evaluate(op.expression) })
  } else if (op.type === 'click' || op.type === 'hover') {
    const point = await pointFor(op)
    await call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: point.x, y: point.y })
    if (op.type === 'click') {
      await call('Input.dispatchMouseEvent', {
        type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1,
      })
      await call('Input.dispatchMouseEvent', {
        type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1,
      })
    }
    results.push({ type: op.type, name: op.name, point })
  } else if (op.type === 'typeText') {
    await call('Input.insertText', { text: op.text })
    results.push({ type: op.type, name: op.name, text: op.text })
  } else if (op.type === 'key') {
    const key = op.key
    const code = op.code || key
    const windowsVirtualKeyCode = op.windowsVirtualKeyCode || 0
    await call('Input.dispatchKeyEvent', { type: 'keyDown', key, code, windowsVirtualKeyCode })
    await call('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode })
    results.push({ type: op.type, name: op.name, key })
  } else if (op.type === 'call') {
    const value = await call(op.method, op.params || {})
    results.push({ type: op.type, name: op.name, method: op.method, value })
  } else if (op.type === 'wait') {
    await new Promise((resolve) => setTimeout(resolve, op.ms))
    results.push({ type: op.type, ms: op.ms })
  } else if (op.type === 'screenshot') {
    const shot = await call('Page.captureScreenshot', { format: 'png', fromSurface: true })
    await fs.writeFile(op.path, Buffer.from(shot.data, 'base64'))
    results.push({ type: op.type, name: op.name, path: op.path })
  } else {
    throw new Error(`Unknown operation type: ${op.type}`)
  }
}

console.log(JSON.stringify({
  target: { id: target.id, title: target.title, url: target.url },
  results,
}, null, 2))
ws.close()
