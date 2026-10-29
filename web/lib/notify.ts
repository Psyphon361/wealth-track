import { toast } from "sonner";
import { toApiMessage, type ApiMessage } from "@/lib/api";

const ERROR_DURATION = 6000;

export const notify = {
  /** Success toast rendering the API's message/description verbatim. */
  success: (payload: Partial<ApiMessage> | undefined) =>
    toast.success(payload?.message ?? "", {
      description: payload?.description,
    }),
  /** Error toast rendering the API error's message/description verbatim. */
  error: (err: unknown) => {
    const { message, description } = toApiMessage(err);
    return toast.error(message, {
      description: description || undefined,
      duration: ERROR_DURATION,
    });
  },
};
