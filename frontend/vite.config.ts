import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import compression from 'vite-plugin-compression'
import { imagetools } from 'vite-imagetools'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    compression({
      algorithm: 'gzip',
      ext: '.gz',
      threshold: 1024,
      deleteOriginFile: false,
    }),
    imagetools(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      'lib': path.resolve(__dirname, './src/lib'),
      'components': path.resolve(__dirname, './src/components'),
      '@swc/helpers/_/_extends': path.resolve(__dirname, './node_modules/@swc/helpers/esm/_extends.js'),
      '@swc/helpers/_/_object_without_properties_loose': path.resolve(__dirname, './node_modules/@swc/helpers/esm/_object_without_properties_loose.js'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            const match = id.match(/node_modules\/(?<pkg>@[^/]+\/[^/]+|[^/]+)/)
            const pkg = match?.groups?.pkg ?? ''
            if (['react', 'react-dom', 'scheduler'].includes(pkg)) return 'react'
            if (pkg === 'react-router-dom' || pkg === 'react-router') return 'router'
            if (pkg === '@tanstack/react-query') return 'query'
            if (pkg === 'lucide-react') return 'icons'
            if (pkg === '@vidstack/react') return 'vidstack'
            if (pkg === '@base-ui/react') return 'base-ui'
          }
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
