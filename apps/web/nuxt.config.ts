declare const process: { env: Record<string, string | undefined> }

export default defineNuxtConfig({
  compatibilityDate: '2026-09-15',
  devtools: { enabled: true },
  ssr: false, // workspace app is a SPA; marketing SSR is separate (spec §21.3)
  typescript: {
    strict: true,
    typeCheck: false
  },
  runtimeConfig: {
    public: {
      // Local demo: the Python analytics control plane owns the pipeline data.
      // Production fronting is the Laravel API (§21.2); override with
      // NUXT_PUBLIC_API_BASE at build/serve time.
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
