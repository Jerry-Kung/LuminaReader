import type { RouteObject } from "react-router-dom";
import NotFound from "../pages/NotFound";
import ReaderPage from "../pages/reader/page";

const routes: RouteObject[] = [
  {
    path: "/",
    element: <ReaderPage />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
