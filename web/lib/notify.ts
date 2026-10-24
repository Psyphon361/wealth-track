import { toast } from "sonner";
import { toApiMessage, type ApiMessage } from "@/lib/api";

const ERROR_DURATION = 6000;

export const notify = {
  saving: (): string | number => toast.loading("Saving…"),
  deleting: (): string | number => toast.loading("Deleting…"),
  /** Success toast rendering the API's message/description verbatim. */
  success: (payload: Partial<ApiMessage> | undefined, id?: string | number) =>
    toast.success(payload?.message ?? "", {
      id,
      description: payload?.description,
    }),
  /** Error toast rendering the API error's message/description verbatim. */
  error: (err: unknown, id?: string | number) => {
    const { message, description } = toApiMessage(err);
    return toast.error(message, {
      id,
      description: description || undefined,
      duration: ERROR_DURATION,
    });
  },
};
