import { BrowserRouter, Route, Routes } from "react-router-dom";
import Harness from "@/pages/Harness";
import Home from "@/pages/Home";
import Chat from "@/pages/Chat";

export default function App() {
  return (
    <BrowserRouter basename="/console">
      <Routes>
        <Route path="/" element={<Chat />} />
        <Route path="/home" element={<Home />} />
        <Route path="/harness" element={<Harness />} />
      </Routes>
    </BrowserRouter>
  );
}
