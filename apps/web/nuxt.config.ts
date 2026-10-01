declare const process: { env: Record<string, string | undefined> }

export default defineNuxtConfig({
  compatibilityDate: '2026-09-15',
  devtools: { enabled: true },
  ssr: false,
  typescript: {
    strict: true,
    typeCheck: false
  },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8100/v1'
    }
  },
  app: {
    head: {
      title: 'DecisionOS',
      htmlAttrs: { lang: 'en', dir: 'ltr' }
    }
  }
})