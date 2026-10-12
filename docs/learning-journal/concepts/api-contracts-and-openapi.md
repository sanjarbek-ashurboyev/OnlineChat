# API contracts and OpenAPI

*First used in [session 025](../sessions/025-api-contract-and-browser-skips.md) (Codex audit M-20).*

## 1. Simple definition

An **API contract** is the promise an API makes: which URLs exist, what to send, what comes back, and what you need
(a token) to call them. **OpenAPI** is a standard file format (YAML or JSON) for writing that promise down. Tools read
it to draw documentation (Swagger UI) or generate client code in other languages.

In this project, **drf-spectacular** writes the OpenAPI file for us by reading our DRF views and serializers. It's
served at `/api/schema/`, with Swagger UI at `/api/schema/swagger-ui/`.

## 2. Why it matters

A generated description is only as good as what the generator can understand. When it can't tell, it **guesses**
and prints a warning ("defaulting to string"). Every guess is a place where the documentation, and any client
generated from it, disagrees with the real server:
- a generated mobile client would read `is_online` as a string and `"true"` would never equal `true`;
- without a security entry, Swagger UI offers no "Authorize" button, and generated clients send no token.

## 3. How it works, step by step

1. drf-spectacular walks every URL and finds its view.
2. For each view it reads the serializer's fields. A `BooleanField` becomes `type: boolean`; a `SerializerMethodField`
   is a Python function, so its type is unknown unless you say it (a return type hint like `-> bool`, or
   `@extend_schema_field(...)`).
3. It reads the view's `authentication_classes` and looks up an **extension** that describes each one. It knows
   SimpleJWT's `JWTAuthentication`, but matches the **exact** class, so our subclass `LastSeenJWTAuthentication`
   needed its own extension.
4. It reads `pagination_class` to describe list responses. It doesn't run our `paginator` property, which picks a
   paginator per request.
5. `@extend_schema(...)` on a view overrides anything it got wrong, e.g. "POST answers with `ChatSerializer`, not
   the input serializer".

## 4. Small example

```python
class PublicUserSerializer(ModelSerializer):
    is_online = SerializerMethodField()

    def get_is_online(self, obj) -> bool:   # without "-> bool" the schema said: type: string
        ...
```

| In the schema | Before | After |
|---|---|---|
| `PublicUser.is_online` | `string` | `boolean` |
| `Chat.participant` | `string` | a `PublicUser` object |
| `POST /chats/{id}/read/` response | no body | `{marked_read: integer}` |
| `POST /chats/` response | `ChatCreate` (only a write-only field: an empty object) | `Chat` |
| History page | numbered pages with `count` | `?cursor=`, no `count` |
| Security | none | `jwtAuth` (Bearer JWT) on every endpoint but login, refresh, register |

## 5. In our project

- **The test:** `root/test_schema.py`. One test runs `manage.py spectacular --fail-on-warn --validate`, so any new
  guess fails the build. The others pin each contract the audit found broken.
- **Authentication:** `accounts/authentication.py`, `LastSeenJWTScheme` (a subclass of drf-spectacular's
  `SimpleJWTScheme`).
- **Field types:** `-> bool` on `get_is_online`; `@extend_schema_field` on `get_participant` and `get_last_message`
  (`chats/serializers.py`).
- **Responses:** `@extend_schema_view(post=...)` on `ChatListCreateAPIView`; `inline_serializer('MarkReadResponse', ...)`
  on `MarkChatReadAPIView`; `pagination_class = HistoryPagination` on `MessageListCreateAPIView`.
- **`COMPONENT_SPLIT_REQUEST: True`** in `SPECTACULAR_SETTINGS`: separate schemas for what you send and what you get
  back. An avatar is a file (`format: binary`) in the request and a link (`format: uri`) in the response. Request
  schemas now end in `Request` (`PatchedProfileRequest`).

## 6. Alternatives

- **Write the OpenAPI file by hand** (design-first). The file is the source of truth, and the code is checked
  against it. More work, and it drifts unless something tests it.
- **Contract tests against real responses:** call each endpoint in a test and validate the JSON against the schema
  (e.g. with `openapi-core`). Catches mismatches the generator can't see, like a view that returns extra keys. More
  setup; worth it once other teams build clients.
- **No schema at all**, just docs in a README. Fine for one browser client written by the same person; not when
  others build clients.

## 7. Common mistakes

- Treating warnings as noise. Each one is a wrong line in the contract.
- "0 errors" from `--validate` only means the file is valid OpenAPI, not that it describes your API.
- Describing the input serializer as the response when the view answers with another serializer.
- Forgetting that a schema generator reads class attributes; logic that picks things per request is invisible to it.
- Leaving the WebSocket out of the picture: OpenAPI describes HTTP only. Our socket's messages are documented in
  the code and the [Channels guide](django-channels-and-redis.md), not in the schema.

## 8. When to use it

Whenever a client you don't write yourself (a mobile app, another team, a partner) will call the API, and before
generating any client code. Make the schema a tested artifact, not a by-product.
