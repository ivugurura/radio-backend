import graphene
import graphql_jwt

from apps.chat.schema.queries import ChatQuery
from apps.medias.schema.mutations import MediasMutations
from apps.medias.schema.queries import MediasQuery
from apps.studio.schema.mutations.members import StudioMemberMutations
from apps.studio.schema.mutations.playback import PlaybackMutations
from apps.studio.schema.mutations.settings import StudioSettingsMutations
from apps.studio.schema.mutations.streaming import StreamingMutations
from apps.studio.schema.mutations.studios import StudioAdminMutations
from apps.studio.schema.queries.dashboard import DashboardQuery
from apps.studio.schema.queries.listeners import ListenerQuery
from apps.studio.schema.queries.members import StudioMembersQuery
from apps.studio.schema.queries.settings import StudioSettingsQuery
from apps.studio.schema.queries.streaming import StreamingQuery
from apps.studio.schema.queries.studios import StudiosQuery
from apps.users.schema.account import AccountMutations, AccountQuery
from apps.users.schema.admin import UserAdminMutations, UserAdminQuery
from apps.users.schema.mutations import UserMutations
from apps.users.schema.queries import UserQuery


class Query(
    UserQuery,
    UserAdminQuery,
    AccountQuery,
    MediasQuery,
    ListenerQuery,
    DashboardQuery,
    StreamingQuery,
    StudioSettingsQuery,
    StudioMembersQuery,
    StudiosQuery,
    ChatQuery,
    graphene.ObjectType,
):
    health = graphene.String(description="Health check field")

    def resolve_health(root, info):
        return "OK"


class Mutation(
    UserMutations,
    UserAdminMutations,
    AccountMutations,
    MediasMutations,
    StreamingMutations,
    PlaybackMutations,
    StudioSettingsMutations,
    StudioMemberMutations,
    StudioAdminMutations,
    graphene.ObjectType,
):
    token_auth = graphql_jwt.ObtainJSONWebToken.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
