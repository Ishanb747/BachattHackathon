import React from "react";
import { createRoot } from "react-dom/client";
import "./atom/tokens.css";
import "./atom/components.css";
import "./app.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
