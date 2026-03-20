import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: resolve(__dirname),
  
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    minify: 'terser',
    sourcemap: false,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        sw: resolve(__dirname, 'sw.js'),
        virtual: resolve(__dirname, 'virtual-scroll.js')
      },
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    },
    // Tree shaking включен по умолчанию
    treeShake: true,
    // Разделение кода
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['virtual-scroll']
        }
      }
    },
    // Сжатие gzip
    brotliSize: true,
    chunkSizeWarningLimit: 500
  },

  server: {
    port: 3000,
    open: true
  },

  optimizeDeps: {
    include: []
  }
});
