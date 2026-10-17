// Theme before first paint: saved choice, else the system setting.
try {
  const saved = localStorage.getItem("cd-theme");
  document.documentElement.dataset.theme = saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
} catch { document.documentElement.dataset.theme = "light"; }
import React from "react";
import { createRoot } from "react-dom/client";
import "./atom/tokens.css";
import "./atom/components.css";
import "./app.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
