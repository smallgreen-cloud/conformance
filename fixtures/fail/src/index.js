export default {
  async fetch(request, env) {
    // CON-3 必 fail：UNDECLARED_API_KEY 未在 secrets manifest 或 wrangler vars 宣告
    const key = env.UNDECLARED_API_KEY;
    return new Response(key ? "ok" : "no key");
  },
};
