import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// NS-21: `npm run build` runs `tsc` first. It must type-check without emitting (no stray .js next to the sources), and the
// jest-dom matchers must come from their vitest entry (the default entry asks for jest's types, which this project does not have).
const root = resolve(__dirname, '..', '..')

describe('build configuration (NS-21)', () => {
  it('tsc does not emit files', () => {
    const tsconfig = JSON.parse(readFileSync(resolve(root, 'tsconfig.json'), 'utf8'))
    expect(tsconfig.compilerOptions.noEmit).toBe(true)
  })

  it('the test setup loads the jest-dom matchers through the vitest entry', () => {
    const setup = readFileSync(resolve(root, 'src', 'test-setup.ts'), 'utf8')
    expect(setup).toContain("@testing-library/jest-dom/vitest")
    expect(setup).not.toMatch(/jest-dom'\s*$/m)
  })
})
