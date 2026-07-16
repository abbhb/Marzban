import fa from "date-fns/locale/fa-IR";
import ru from "date-fns/locale/ru";
import zh from "date-fns/locale/zh-CN";
import { registerLocale } from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css";

registerLocale("zh-cn", zh);
registerLocale("ru", ru);
registerLocale("fa", fa);
