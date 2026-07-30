export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") {
      await env.DB.prepare("SELECT 1").first();
      return new Response("ok");
    }
    return new Response("fixture", { status: 200 });
  },
};
