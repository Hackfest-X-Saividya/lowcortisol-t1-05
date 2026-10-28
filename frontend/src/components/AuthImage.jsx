// An <img> for a protected backend file (sends the bearer token, shows a blob URL).
import { useEffect, useState } from "react";
import { fileUrl } from "../lib/api.js";

export default function AuthImage({ fileId, token, alt = "", onShown, className, fallback = null }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setFailed(false);
    if (!fileId) {
      setSrc(null);
      return undefined;
    }
    fileUrl(fileId, token)
      .then((u) => live && setSrc(u))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [fileId, token]);
  if (failed || !src) return fallback;
  return <img className={className} src={src} alt={alt} onLoad={() => onShown?.(fileId)} draggable={false} />;
}
