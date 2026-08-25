"""GraphQL operations of the Domaine's application.

These strings reproduce EXACTLY what the page emits. That is not fussiness:
the site's web application firewall validates the shape and the length of the
parameters, and rejects any forged request — with a 400, then an anti-bot
challenge — even when it is semantically equivalent.

Sleeper therefore replays the application's public contract without diverting
it: only the VARIABLES change from one call to the next. Any change to one of
these strings must be preceded by a fresh discovery run
(tools/discover_api.py) and reflected in docs/api.md.

Recorded on 2026-08-25 from encheres-domaine.gouv.fr.
"""

from __future__ import annotations

from typing import Final

#: Path of the GraphQL gateway, relative to `network.base_url`.
GRAPHQL_PATH: Final = "/gateway/magento/graphql/"

#: Paginated list of sales, filterable on `auction_auto_status`.
#: operationName = 'getAuctions'
SALES_LIST: Final = (
    "query getAuctions($currentPage:Int$filter:AuctionFiltersInput$pageSize:Int$sort:AuctionS"
    "ortsInput){auctionsList(currentPage:$currentPage filter:$filter pageSize:$pageSize sort:"
    "$sort){items{auction_auto_status auction_documents{pdf_specifications{label url_path typ"
    "e size __typename}__typename}auction_number_of_lots categories{name __typename}descripti"
    "on dnid_auction_id end_date image_path location name offers_submission_deadline professi"
    "onal_only sales_inspector_label start_date status_text type type_text __typename}page_in"
    "fo{total_pages __typename}total_count __typename}}"
)

#: Header of a sale: title, dates, regional directorate.
#: operationName = 'getAuctionHeaderInfos'
SALE_HEADER: Final = (
    "query getAuctionHeaderInfos($id:Int!){auction(id:$id){auction_additional_status auction_"
    "auto_status auction_documents{conditions_of_sale{label url_path type size __typename}pdf"
    "_specifications{label url_path type size __typename}sales_catalog{label url_path type si"
    "ze __typename}__typename}auction_urls{first_auction_partnersite_url{label url_path __typ"
    "ename}second_auction_partnersite_url{label url_path __typename}physical_register_url{lab"
    "el url_path __typename}__typename}description dnid_auction_id end_date live_end_date ima"
    "ge_path location name offers_submission_deadline sales_inspector_label start_date status"
    "_text type type_text __typename}}"
)

#: Lots of a sale: prices, collection point, trade-only flag.
#: operationName = 'getAuctionLots'
SALE_LOTS: Final = (
    "query getAuctionLots($currentPage:Int$filter:ProductAttributeFilterInput$pageSize:Int$so"
    "rt:ProductAttributeSortInput){products(currentPage:$currentPage filter:$filter pageSize:"
    "$pageSize sort:$sort){...ProductsFragment __typename}}fragment ProductsFragment on Produ"
    "cts{items{__typename auction auction_auto_status auction_type bid_winner_amount descript"
    "ion{html __typename}dropoff_location_id dropoff_location{city postcode __typename}end_au"
    "ction_lot_at end_date has_lost has_won id last_bid lot_number location lot_status lot_st"
    "atus_label luxury luxury_label name offers_submission_deadline price_auction professiona"
    "l_only reserve_price sku sales_inspector_data{cav_name __typename}short_description{html"
    " __typename}small_image{url __typename}start_auction_lot_at start_date uid url_key}page_"
    "info{total_pages __typename}total_count __typename}"
)

#: Full listing of a lot, with its vehicle attributes.
#: operationName = 'getProductPageMain'
LOT_MAIN: Final = (
    "query getProductPageMain($urlKey:String!){products(filter:{url_key:{eq:$urlKey}}){items{"
    "uid __typename auction_type categories{uid breadcrumbs{category_uid category_name catego"
    "ry_url_path category_level __typename}image name url_key url_path __typename}custom_attr"
    "ibutes{attribute_metadata{uid code label attribute_labels{store_code label __typename}da"
    "ta_type is_system entity_type ...on ProductAttributeMetadata{used_in_components __typena"
    "me}__typename}entered_attribute_value{value __typename}selected_attribute_options{attrib"
    "ute_option{uid label is_default __typename}__typename}__typename}description{html __type"
    "name}dropoff_location_id dropoff_location_fo{address address_complement address_compleme"
    "nt_bis city dnid_dropoff_location_id name postcode published __typename}dropoff_location"
    "{city postcode __typename}contact_dropoff_location{dnid_contact_dropoff_location_id emai"
    "l function mobile_phone name physical_schedule status tel_schedule telephone __typename}"
    "id lot_number media_gallery_entries{uid label position disabled file __typename}name pro"
    "duct_documents{url_path label __typename}professional_only sales_inspector_data{cav_name"
    " __typename}short_description{html __typename}small_image{url __typename}sku tax_info{la"
    "bel percent __typename}state_property_tax url_key}__typename}}"
)

#: Bidding panel of a lot: starting price, last bid, status.
#: operationName = 'getProductPageSide'
LOT_BIDDING: Final = (
    "query getProductPageSide($urlKey:String!){products(filter:{url_key:{eq:$urlKey}}){items{"
    "ape_authorization ape_restriction not_conforme auction auction_documents{pdf_specificati"
    "ons{label url_path type size __typename}__typename}auction_auto_status auction_name auct"
    "ion_type auction_type_label auction_steps auction_urls{first_auction_partnersite_url{lab"
    "el url_path __typename}second_auction_partnersite_url{label url_path __typename}physical"
    "_register_url{label url_path __typename}__typename}bid_winner_amount end_auction_lot_at "
    "end_date has_lost has_won id last_bid lot_number location lot_status lot_status_label na"
    "me price_auction professional_only reserve_price sales_inspector_data{cav_name __typenam"
    "e}start_auction_lot_at start_date uid url_key __typename}__typename}}"
)

#: `operationName` expected by the gateway for each request.
OPERATION_NAME: Final[dict[str, str]] = {
    SALES_LIST: "getAuctions",
    SALE_HEADER: "getAuctionHeaderInfos",
    SALE_LOTS: "getAuctionLots",
    LOT_MAIN: "getProductPageMain",
    LOT_BIDDING: "getProductPageSide",
}
