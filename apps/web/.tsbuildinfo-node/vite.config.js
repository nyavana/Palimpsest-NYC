var _a;
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: {
        port: 5173,
        host: true,
        proxy: {
            "/api": {
                target: (_a = process.env.VITE_API_BASE_URL) !== null && _a !== void 0 ? _a : "http://localhost:8000",
                changeOrigin: true,
                rewrite: function (p) { return p.replace(/^\/api/, ""); },
            },
        },
    },
});
