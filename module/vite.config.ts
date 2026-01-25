import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'
import version from '../scripts/module_version';

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [version(), dts({ insertTypesEntry: true })],
  publicDir: false,

  esbuild: {
	drop: ['console', 'debugger'],
  },

  build: {

	outDir:"dist",
    lib: {
      entry: resolve(__dirname, 'src/module.ts'),
      name: 'ThreejsBlendertools',
	  formats: ['es'],
    }, 
	
    rollupOptions: { 
      external: [ 'three' ],
      output: { 
        globals: {
          'three': 'THREE'
        },
      },
    },
  },
})