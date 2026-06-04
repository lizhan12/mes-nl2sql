import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "@/pages/Home";
import Chat from "@/pages/Chat";

export default function App() {
  return (
    <BrowserRouter basename="/console">
      <Routes>
        <Route path="/" element={<Chat />} />
        <Route path="/home" element={<Home />} />
      </Routes>
    </BrowserRouter>
  );
}
