// Serves the 3D face builder (the "3D MODEL" folder next to this project) under /nishaan3d/,
// read-only, from the same origin as this app, so the witness window can embed its editor.
// The 3D app's files are used exactly as they are: its page loads ../../assets and
// ../../node_modules/three relative to src/renderer/index.html, which resolve inside the
// same prefix. Only the folders that page needs are served.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const PREFIX = "/nishaan3d/";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(process.env.NISHAAN_3D_DIR || path.join(HERE, "..", "..", "3D MODEL"));
const ALLOWED = ["src/renderer/", "assets/", "node_modules/three/"];

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".bin": "application/octet-stream",
  ".obj": "text/plain; charset=utf-8",
  ".mtl": "text/plain; charset=utf-8",
  ".fbx": "application/octet-stream",
  ".wasm": "application/wasm",
};

function resolveFile(urlPath) {
  let rel;
  try {
    rel = decodeURIComponent(urlPath.slice(PREFIX.length).split("?")[0].split("#")[0]);
  } catch {
    return null;
  }
  rel = rel.replace(/\\/g, "/");
  if (!rel || rel.endsWith("/")) rel += "index.html";
  // check the folder after resolving, so ../ (also %2F-encoded) cannot leave it
  const file = path.resolve(ROOT, rel);
  const inside = path.relative(ROOT, file).split(path.sep).join("/");
  if (inside.startsWith("..") || path.isAbsolute(inside)) return null;
  if (!ALLOWED.some((a) => inside.startsWith(a))) return null;
  return file;
}

function middleware(req, res, next) {
  if (!req.url || !req.url.startsWith(PREFIX)) return next();
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.statusCode = 405;
    return res.end();
  }
  const file = resolveFile(req.url);
  let stat = null;
  try {
    stat = file && fs.statSync(file);
  } catch {
    stat = null;
  }
  if (!stat || !stat.isFile()) {
    res.statusCode = 404;
    return res.end("Not found");
  }
  const type = TYPES[path.extname(file).toLowerCase()] || "application/octet-stream";
  res.setHeader("Content-Type", type);
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Accept-Ranges", "bytes");

  // byte ranges (video previews seek with them)
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");
  let start = 0;
  let end = stat.size - 1;
  if (range && (range[1] || range[2])) {
    if (range[1]) {
      start = Number(range[1]);
      if (range[2]) end = Math.min(Number(range[2]), end);
    } else {
      start = Math.max(0, stat.size - Number(range[2]));
    }
    if (start > end || start >= stat.size) {
      res.statusCode = 416;
      res.setHeader("Content-Range", `bytes */${stat.size}`);
      return res.end();
    }
    res.statusCode = 206;
    res.setHeader("Content-Range", `bytes ${start}-${end}/${stat.size}`);
  }
  res.setHeader("Content-Length", end - start + 1);
  if (req.method === "HEAD") return res.end();
  fs.createReadStream(file, { start, end }).on("error", () => res.destroy()).pipe(res);
}

export default function nishaan3d() {
  return {
    name: "nishaan-3d-face-builder",
    configureServer(server) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}
