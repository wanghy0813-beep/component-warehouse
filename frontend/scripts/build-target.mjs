const target = process.argv[2]

if (!['personal', 'team', 'desktop'].includes(target)) {
  throw new Error(`Unsupported frontend build target: ${target || '(missing)'}`)
}

process.env.VITE_APP_TARGET = target === 'desktop' ? 'personal' : target
if (target === 'desktop') process.env.VITE_DESKTOP = '1'

const { build } = await import('vite')
await build()
