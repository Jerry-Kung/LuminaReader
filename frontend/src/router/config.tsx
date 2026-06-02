import type { RouteObject } from "react-router-dom";
import NotFound from "../pages/NotFound";
import BookshelfPage from "../pages/bookshelf/page";
import ReaderPage from "../pages/reader/page";
import SettingsPage from "../pages/settings/page";

const routes: RouteObject[] = [
  {
    path: "/",
    element: <BookshelfPage />,
  },
  {
    path: "/reader/:pdf_id",
    element: <ReaderPage />,
  },
  {
    path: "/settings",
    element: <SettingsPage />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
