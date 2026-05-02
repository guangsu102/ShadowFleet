--
-- PostgreSQL database dump
--

\restrict ntTF5yb9S4Z2SJZfPXiKoAhvVZOom9LsLjpjNZia7xmzMhCo5YpomBRWW4UvNB8

-- Dumped from database version 16.12
-- Dumped by pg_dump version 16.12

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: failed_jobs; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.failed_jobs (
    id bigint NOT NULL,
    connection text NOT NULL,
    queue text NOT NULL,
    payload text NOT NULL,
    exception text NOT NULL,
    failed_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.failed_jobs OWNER TO tanxuan;

--
-- Name: failed_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.failed_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.failed_jobs_id_seq OWNER TO tanxuan;

--
-- Name: failed_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.failed_jobs_id_seq OWNED BY public.failed_jobs.id;


--
-- Name: migrations; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.migrations (
    id integer NOT NULL,
    migration character varying(255) NOT NULL,
    batch integer NOT NULL
);


ALTER TABLE public.migrations OWNER TO tanxuan;

--
-- Name: migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.migrations_id_seq OWNER TO tanxuan;

--
-- Name: migrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.migrations_id_seq OWNED BY public.migrations.id;


--
-- Name: personal_access_tokens; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.personal_access_tokens (
    id bigint NOT NULL,
    tokenable_type character varying(255) NOT NULL,
    tokenable_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    token character varying(64) NOT NULL,
    abilities text,
    last_used_at timestamp(0) without time zone,
    expires_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone,
    updated_at timestamp(0) without time zone
);


ALTER TABLE public.personal_access_tokens OWNER TO tanxuan;

--
-- Name: personal_access_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.personal_access_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personal_access_tokens_id_seq OWNER TO tanxuan;

--
-- Name: personal_access_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.personal_access_tokens_id_seq OWNED BY public.personal_access_tokens.id;


--
-- Name: v2_commission_log; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_commission_log (
    id integer NOT NULL,
    invite_user_id integer NOT NULL,
    user_id integer NOT NULL,
    trade_no character(36) NOT NULL,
    order_amount integer NOT NULL,
    get_amount integer NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_commission_log OWNER TO tanxuan;

--
-- Name: v2_commission_log_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_commission_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_commission_log_id_seq OWNER TO tanxuan;

--
-- Name: v2_commission_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_commission_log_id_seq OWNED BY public.v2_commission_log.id;


--
-- Name: v2_coupon; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_coupon (
    id integer NOT NULL,
    code character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    type integer NOT NULL,
    value integer NOT NULL,
    show boolean DEFAULT false NOT NULL,
    limit_use integer,
    limit_use_with_user integer,
    limit_plan_ids character varying(255),
    limit_period character varying(255),
    started_at integer NOT NULL,
    ended_at integer NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_coupon OWNER TO tanxuan;

--
-- Name: v2_coupon_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_coupon_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_coupon_id_seq OWNER TO tanxuan;

--
-- Name: v2_coupon_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_coupon_id_seq OWNED BY public.v2_coupon.id;


--
-- Name: v2_gift_card_code; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_gift_card_code (
    id bigint NOT NULL,
    template_id integer NOT NULL,
    code character varying(32) NOT NULL,
    batch_id character varying(32),
    status smallint DEFAULT '0'::smallint NOT NULL,
    user_id integer,
    used_at integer,
    expires_at integer,
    actual_rewards json,
    usage_count integer DEFAULT 0 NOT NULL,
    max_usage integer DEFAULT 1 NOT NULL,
    metadata json,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_gift_card_code OWNER TO tanxuan;

--
-- Name: COLUMN v2_gift_card_code.template_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.template_id IS '模板ID';


--
-- Name: COLUMN v2_gift_card_code.code; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.code IS '兑换码';


--
-- Name: COLUMN v2_gift_card_code.batch_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.batch_id IS '批次ID';


--
-- Name: COLUMN v2_gift_card_code.status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.status IS '状态：0未使用 1已使用 2已过期 3已禁用';


--
-- Name: COLUMN v2_gift_card_code.user_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.user_id IS '使用用户ID';


--
-- Name: COLUMN v2_gift_card_code.used_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.used_at IS '使用时间';


--
-- Name: COLUMN v2_gift_card_code.expires_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.expires_at IS '过期时间';


--
-- Name: COLUMN v2_gift_card_code.actual_rewards; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.actual_rewards IS '实际获得的奖励(用于盲盒等)';


--
-- Name: COLUMN v2_gift_card_code.usage_count; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.usage_count IS '使用次数(分享卡)';


--
-- Name: COLUMN v2_gift_card_code.max_usage; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.max_usage IS '最大使用次数';


--
-- Name: COLUMN v2_gift_card_code.metadata; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_code.metadata IS '额外数据';


--
-- Name: v2_gift_card_code_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_gift_card_code_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_gift_card_code_id_seq OWNER TO tanxuan;

--
-- Name: v2_gift_card_code_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_gift_card_code_id_seq OWNED BY public.v2_gift_card_code.id;


--
-- Name: v2_gift_card_template; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_gift_card_template (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    type smallint NOT NULL,
    status smallint DEFAULT '1'::smallint NOT NULL,
    conditions json,
    rewards json NOT NULL,
    limits json,
    special_config json,
    icon character varying(255),
    background_image character varying(255),
    theme_color character varying(7) DEFAULT '#1890ff'::character varying NOT NULL,
    sort integer DEFAULT 0 NOT NULL,
    admin_id integer NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_gift_card_template OWNER TO tanxuan;

--
-- Name: COLUMN v2_gift_card_template.name; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.name IS '礼品卡名称';


--
-- Name: COLUMN v2_gift_card_template.description; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.description IS '礼品卡描述';


--
-- Name: COLUMN v2_gift_card_template.type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.type IS '卡片类型：1余额 2有效期 3流量 4重置包 5套餐 6组合 7盲盒 8任务 9等级 10节日';


--
-- Name: COLUMN v2_gift_card_template.status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.status IS '状态：0禁用 1启用';


--
-- Name: COLUMN v2_gift_card_template.conditions; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.conditions IS '使用条件配置';


--
-- Name: COLUMN v2_gift_card_template.rewards; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.rewards IS '奖励配置';


--
-- Name: COLUMN v2_gift_card_template.limits; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.limits IS '限制条件';


--
-- Name: COLUMN v2_gift_card_template.special_config; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.special_config IS '特殊配置(节日时间、等级倍率等)';


--
-- Name: COLUMN v2_gift_card_template.icon; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.icon IS '卡片图标';


--
-- Name: COLUMN v2_gift_card_template.background_image; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.background_image IS '背景图片URL';


--
-- Name: COLUMN v2_gift_card_template.theme_color; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.theme_color IS '主题色';


--
-- Name: COLUMN v2_gift_card_template.sort; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.sort IS '排序';


--
-- Name: COLUMN v2_gift_card_template.admin_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_template.admin_id IS '创建管理员ID';


--
-- Name: v2_gift_card_template_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_gift_card_template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_gift_card_template_id_seq OWNER TO tanxuan;

--
-- Name: v2_gift_card_template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_gift_card_template_id_seq OWNED BY public.v2_gift_card_template.id;


--
-- Name: v2_gift_card_usage; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_gift_card_usage (
    id bigint NOT NULL,
    code_id integer NOT NULL,
    template_id integer NOT NULL,
    user_id integer NOT NULL,
    invite_user_id integer,
    rewards_given json NOT NULL,
    invite_rewards json,
    user_level_at_use integer,
    plan_id_at_use integer,
    multiplier_applied numeric(3,2) DEFAULT '1'::numeric NOT NULL,
    ip_address character varying(45),
    user_agent text,
    notes text,
    created_at integer NOT NULL
);


ALTER TABLE public.v2_gift_card_usage OWNER TO tanxuan;

--
-- Name: COLUMN v2_gift_card_usage.code_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.code_id IS '兑换码ID';


--
-- Name: COLUMN v2_gift_card_usage.template_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.template_id IS '模板ID';


--
-- Name: COLUMN v2_gift_card_usage.user_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.user_id IS '使用用户ID';


--
-- Name: COLUMN v2_gift_card_usage.invite_user_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.invite_user_id IS '邀请人ID';


--
-- Name: COLUMN v2_gift_card_usage.rewards_given; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.rewards_given IS '实际发放的奖励';


--
-- Name: COLUMN v2_gift_card_usage.invite_rewards; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.invite_rewards IS '邀请人获得的奖励';


--
-- Name: COLUMN v2_gift_card_usage.user_level_at_use; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.user_level_at_use IS '使用时用户等级';


--
-- Name: COLUMN v2_gift_card_usage.plan_id_at_use; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.plan_id_at_use IS '使用时用户套餐ID';


--
-- Name: COLUMN v2_gift_card_usage.multiplier_applied; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.multiplier_applied IS '应用的倍率';


--
-- Name: COLUMN v2_gift_card_usage.ip_address; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.ip_address IS '使用IP地址';


--
-- Name: COLUMN v2_gift_card_usage.user_agent; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.user_agent IS '用户代理';


--
-- Name: COLUMN v2_gift_card_usage.notes; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_gift_card_usage.notes IS '备注';


--
-- Name: v2_gift_card_usage_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_gift_card_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_gift_card_usage_id_seq OWNER TO tanxuan;

--
-- Name: v2_gift_card_usage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_gift_card_usage_id_seq OWNED BY public.v2_gift_card_usage.id;


--
-- Name: v2_invite_code; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_invite_code (
    id integer NOT NULL,
    user_id integer NOT NULL,
    code character(32) NOT NULL,
    status boolean DEFAULT false NOT NULL,
    pv integer DEFAULT 0 NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_invite_code OWNER TO tanxuan;

--
-- Name: v2_invite_code_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_invite_code_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_invite_code_id_seq OWNER TO tanxuan;

--
-- Name: v2_invite_code_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_invite_code_id_seq OWNED BY public.v2_invite_code.id;


--
-- Name: v2_knowledge; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_knowledge (
    id integer NOT NULL,
    language character(5) NOT NULL,
    category character varying(255) NOT NULL,
    title character varying(255) NOT NULL,
    body text NOT NULL,
    sort integer,
    show boolean DEFAULT false NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_knowledge OWNER TO tanxuan;

--
-- Name: COLUMN v2_knowledge.language; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.language IS '語言';


--
-- Name: COLUMN v2_knowledge.category; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.category IS '分類名';


--
-- Name: COLUMN v2_knowledge.title; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.title IS '標題';


--
-- Name: COLUMN v2_knowledge.body; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.body IS '內容';


--
-- Name: COLUMN v2_knowledge.sort; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.sort IS '排序';


--
-- Name: COLUMN v2_knowledge.show; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.show IS '顯示';


--
-- Name: COLUMN v2_knowledge.created_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.created_at IS '創建時間';


--
-- Name: COLUMN v2_knowledge.updated_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_knowledge.updated_at IS '更新時間';


--
-- Name: v2_knowledge_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_knowledge_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_knowledge_id_seq OWNER TO tanxuan;

--
-- Name: v2_knowledge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_knowledge_id_seq OWNED BY public.v2_knowledge.id;


--
-- Name: v2_log; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_log (
    id integer NOT NULL,
    title text NOT NULL,
    level character varying(11),
    host character varying(255),
    uri character varying(255) NOT NULL,
    method character varying(11) NOT NULL,
    data text,
    ip character varying(128),
    context text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_log OWNER TO tanxuan;

--
-- Name: v2_log_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_log_id_seq OWNER TO tanxuan;

--
-- Name: v2_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_log_id_seq OWNED BY public.v2_log.id;


--
-- Name: v2_mail_log; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_mail_log (
    id integer NOT NULL,
    email character varying(64) NOT NULL,
    subject character varying(255) NOT NULL,
    template_name character varying(255) NOT NULL,
    error text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_mail_log OWNER TO tanxuan;

--
-- Name: v2_mail_log_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_mail_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_mail_log_id_seq OWNER TO tanxuan;

--
-- Name: v2_mail_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_mail_log_id_seq OWNED BY public.v2_mail_log.id;


--
-- Name: v2_notice; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_notice (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    content text NOT NULL,
    show boolean DEFAULT false NOT NULL,
    img_url character varying(255),
    tags character varying(255),
    created_at integer NOT NULL,
    updated_at integer NOT NULL,
    sort integer
);


ALTER TABLE public.v2_notice OWNER TO tanxuan;

--
-- Name: v2_notice_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_notice_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_notice_id_seq OWNER TO tanxuan;

--
-- Name: v2_notice_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_notice_id_seq OWNED BY public.v2_notice.id;


--
-- Name: v2_order; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_order (
    id integer NOT NULL,
    invite_user_id integer,
    user_id integer NOT NULL,
    plan_id integer NOT NULL,
    coupon_id integer,
    payment_id integer,
    type integer NOT NULL,
    period character varying(255) NOT NULL,
    trade_no character varying(36) NOT NULL,
    callback_no character varying(255),
    total_amount integer NOT NULL,
    handling_amount integer,
    discount_amount integer,
    surplus_amount integer,
    refund_amount integer,
    balance_amount integer,
    surplus_order_ids text,
    status integer DEFAULT 0 NOT NULL,
    commission_status integer DEFAULT 0 NOT NULL,
    commission_balance integer DEFAULT 0 NOT NULL,
    actual_commission_balance integer,
    paid_at integer,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_order OWNER TO tanxuan;

--
-- Name: COLUMN v2_order.type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.type IS '1新购2续费3升级';


--
-- Name: COLUMN v2_order.surplus_amount; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.surplus_amount IS '剩余价值';


--
-- Name: COLUMN v2_order.refund_amount; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.refund_amount IS '退款金额';


--
-- Name: COLUMN v2_order.balance_amount; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.balance_amount IS '使用余额';


--
-- Name: COLUMN v2_order.surplus_order_ids; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.surplus_order_ids IS '折抵订单';


--
-- Name: COLUMN v2_order.status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.status IS '0待支付1开通中2已取消3已完成4已折抵';


--
-- Name: COLUMN v2_order.commission_status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.commission_status IS '0待确认1发放中2有效3无效';


--
-- Name: COLUMN v2_order.actual_commission_balance; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_order.actual_commission_balance IS '实际支付佣金';


--
-- Name: v2_order_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_order_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_order_id_seq OWNER TO tanxuan;

--
-- Name: v2_order_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_order_id_seq OWNED BY public.v2_order.id;


--
-- Name: v2_payment; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_payment (
    id integer NOT NULL,
    uuid character(32) NOT NULL,
    payment character varying(16) NOT NULL,
    name character varying(255) NOT NULL,
    icon text,
    config text NOT NULL,
    notify_domain character varying(128),
    handling_fee_fixed integer,
    handling_fee_percent numeric(5,2),
    enable boolean DEFAULT false NOT NULL,
    sort integer,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_payment OWNER TO tanxuan;

--
-- Name: v2_payment_callback_logs; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_payment_callback_logs (
    id bigint NOT NULL,
    payment_method character varying(50) NOT NULL,
    payment_uuid character varying(50) NOT NULL,
    trade_no character varying(100) NOT NULL,
    callback_no character varying(100) NOT NULL,
    request_ip character varying(45),
    request_params text,
    sign_verified boolean DEFAULT false NOT NULL,
    status_verified boolean DEFAULT false NOT NULL,
    verify_result character varying(50),
    error_message text,
    created_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.v2_payment_callback_logs OWNER TO tanxuan;

--
-- Name: COLUMN v2_payment_callback_logs.payment_method; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.payment_method IS '支付方式';


--
-- Name: COLUMN v2_payment_callback_logs.payment_uuid; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.payment_uuid IS '支付UUID';


--
-- Name: COLUMN v2_payment_callback_logs.trade_no; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.trade_no IS '订单号';


--
-- Name: COLUMN v2_payment_callback_logs.callback_no; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.callback_no IS '回调流水号';


--
-- Name: COLUMN v2_payment_callback_logs.request_ip; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.request_ip IS '请求IP';


--
-- Name: COLUMN v2_payment_callback_logs.request_params; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.request_params IS '请求参数';


--
-- Name: COLUMN v2_payment_callback_logs.sign_verified; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.sign_verified IS '签名是否验证通过';


--
-- Name: COLUMN v2_payment_callback_logs.status_verified; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.status_verified IS '状态是否验证通过';


--
-- Name: COLUMN v2_payment_callback_logs.verify_result; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.verify_result IS '验证结果';


--
-- Name: COLUMN v2_payment_callback_logs.error_message; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.error_message IS '错误信息';


--
-- Name: COLUMN v2_payment_callback_logs.created_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_payment_callback_logs.created_at IS '创建时间';


--
-- Name: v2_payment_callback_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_payment_callback_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_payment_callback_logs_id_seq OWNER TO tanxuan;

--
-- Name: v2_payment_callback_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_payment_callback_logs_id_seq OWNED BY public.v2_payment_callback_logs.id;


--
-- Name: v2_payment_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_payment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_payment_id_seq OWNER TO tanxuan;

--
-- Name: v2_payment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_payment_id_seq OWNED BY public.v2_payment.id;


--
-- Name: v2_plan; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_plan (
    id integer NOT NULL,
    group_id integer,
    transfer_enable bigint,
    name character varying(255) NOT NULL,
    speed_limit integer,
    show boolean DEFAULT false NOT NULL,
    sort integer,
    renew boolean DEFAULT true NOT NULL,
    content text,
    reset_traffic_method integer DEFAULT 0,
    capacity_limit integer DEFAULT 0,
    created_at integer NOT NULL,
    updated_at integer NOT NULL,
    prices json,
    sell boolean DEFAULT false NOT NULL,
    device_limit integer,
    tags json
);


ALTER TABLE public.v2_plan OWNER TO tanxuan;

--
-- Name: COLUMN v2_plan.transfer_enable; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.transfer_enable IS 'Transfer limit in bytes';


--
-- Name: COLUMN v2_plan.speed_limit; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.speed_limit IS 'Speed limit in Mbps, 0 for unlimited';


--
-- Name: COLUMN v2_plan.reset_traffic_method; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.reset_traffic_method IS '重置流量方式:null跟随系统设置、0每月1号、1按月重置、2不重置、3每年1月1日、4按年重置';


--
-- Name: COLUMN v2_plan.capacity_limit; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.capacity_limit IS '0 for unlimited';


--
-- Name: COLUMN v2_plan.prices; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.prices IS 'Store different duration prices and reset traffic price';


--
-- Name: COLUMN v2_plan.sell; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plan.sell IS 'is sell';


--
-- Name: v2_plan_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_plan_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_plan_id_seq OWNER TO tanxuan;

--
-- Name: v2_plan_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_plan_id_seq OWNED BY public.v2_plan.id;


--
-- Name: v2_plugins; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_plugins (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    code character varying(255) NOT NULL,
    version character varying(50) NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    config json,
    installed_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone,
    updated_at timestamp(0) without time zone,
    type character varying(20) DEFAULT 'feature'::character varying NOT NULL
);


ALTER TABLE public.v2_plugins OWNER TO tanxuan;

--
-- Name: COLUMN v2_plugins.type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_plugins.type IS '插件类型：feature功能性，payment支付型';


--
-- Name: v2_plugins_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_plugins_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_plugins_id_seq OWNER TO tanxuan;

--
-- Name: v2_plugins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_plugins_id_seq OWNED BY public.v2_plugins.id;


--
-- Name: v2_server; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_server (
    id bigint NOT NULL,
    type character varying(255) NOT NULL,
    code character varying(255),
    parent_id integer,
    group_ids json,
    route_ids json,
    name character varying(255) NOT NULL,
    rate numeric(8,2) NOT NULL,
    tags json,
    host character varying(255) NOT NULL,
    port character varying(255) NOT NULL,
    server_port integer NOT NULL,
    protocol_settings json,
    show boolean DEFAULT false NOT NULL,
    sort integer,
    created_at timestamp(0) without time zone,
    updated_at timestamp(0) without time zone,
    rate_time_enable boolean DEFAULT false NOT NULL,
    rate_time_ranges json
);


ALTER TABLE public.v2_server OWNER TO tanxuan;

--
-- Name: COLUMN v2_server.type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.type IS 'Server Type';


--
-- Name: COLUMN v2_server.code; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.code IS 'Server Spectific Key';


--
-- Name: COLUMN v2_server.parent_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.parent_id IS 'Parent Server ID';


--
-- Name: COLUMN v2_server.group_ids; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.group_ids IS 'Group ID';


--
-- Name: COLUMN v2_server.route_ids; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.route_ids IS 'Route ID';


--
-- Name: COLUMN v2_server.name; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.name IS 'Server Name';


--
-- Name: COLUMN v2_server.rate; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.rate IS 'Traffic Rate';


--
-- Name: COLUMN v2_server.tags; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.tags IS 'Server Tags';


--
-- Name: COLUMN v2_server.host; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.host IS 'Server Host';


--
-- Name: COLUMN v2_server.port; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.port IS 'Client Port';


--
-- Name: COLUMN v2_server.server_port; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.server_port IS 'Server Port';


--
-- Name: COLUMN v2_server.show; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.show IS 'Show in List';


--
-- Name: COLUMN v2_server.rate_time_enable; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.rate_time_enable IS '是否启用动态倍率';


--
-- Name: COLUMN v2_server.rate_time_ranges; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_server.rate_time_ranges IS '动态倍率规则';


--
-- Name: v2_server_group; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_server_group (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_server_group OWNER TO tanxuan;

--
-- Name: v2_server_group_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_server_group_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_server_group_id_seq OWNER TO tanxuan;

--
-- Name: v2_server_group_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_server_group_id_seq OWNED BY public.v2_server_group.id;


--
-- Name: v2_server_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_server_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_server_id_seq OWNER TO tanxuan;

--
-- Name: v2_server_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_server_id_seq OWNED BY public.v2_server.id;


--
-- Name: v2_server_route; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_server_route (
    id integer NOT NULL,
    remarks character varying(255) NOT NULL,
    match text NOT NULL,
    action character varying(11) NOT NULL,
    action_value character varying(255),
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_server_route OWNER TO tanxuan;

--
-- Name: v2_server_route_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_server_route_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_server_route_id_seq OWNER TO tanxuan;

--
-- Name: v2_server_route_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_server_route_id_seq OWNED BY public.v2_server_route.id;


--
-- Name: v2_settings; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_settings (
    id bigint NOT NULL,
    "group" character varying(255),
    type character varying(255),
    name character varying(255) NOT NULL,
    value text,
    created_at timestamp(0) without time zone,
    updated_at timestamp(0) without time zone
);


ALTER TABLE public.v2_settings OWNER TO tanxuan;

--
-- Name: COLUMN v2_settings."group"; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_settings."group" IS '设置分组';


--
-- Name: COLUMN v2_settings.type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_settings.type IS '设置类型';


--
-- Name: COLUMN v2_settings.name; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_settings.name IS '设置名称';


--
-- Name: v2_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_settings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_settings_id_seq OWNER TO tanxuan;

--
-- Name: v2_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_settings_id_seq OWNED BY public.v2_settings.id;


--
-- Name: v2_stat; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_stat (
    id integer NOT NULL,
    record_at integer NOT NULL,
    record_type character(1) NOT NULL,
    order_count integer NOT NULL,
    order_total integer NOT NULL,
    commission_count integer NOT NULL,
    commission_total integer NOT NULL,
    paid_count integer NOT NULL,
    paid_total integer NOT NULL,
    register_count integer NOT NULL,
    invite_count integer NOT NULL,
    transfer_used_total character varying(32) NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_stat OWNER TO tanxuan;

--
-- Name: COLUMN v2_stat.order_count; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat.order_count IS '订单数量';


--
-- Name: COLUMN v2_stat.order_total; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat.order_total IS '订单合计';


--
-- Name: COLUMN v2_stat.commission_total; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat.commission_total IS '佣金合计';


--
-- Name: v2_stat_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_stat_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_stat_id_seq OWNER TO tanxuan;

--
-- Name: v2_stat_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_stat_id_seq OWNED BY public.v2_stat.id;


--
-- Name: v2_stat_server; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_stat_server (
    id integer NOT NULL,
    server_id integer NOT NULL,
    server_type character(11) NOT NULL,
    u bigint NOT NULL,
    d bigint NOT NULL,
    record_type character(1) NOT NULL,
    record_at integer NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_stat_server OWNER TO tanxuan;

--
-- Name: COLUMN v2_stat_server.server_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat_server.server_id IS '节点id';


--
-- Name: COLUMN v2_stat_server.server_type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat_server.server_type IS '节点类型';


--
-- Name: COLUMN v2_stat_server.record_type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat_server.record_type IS 'd day m month';


--
-- Name: COLUMN v2_stat_server.record_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_stat_server.record_at IS '记录时间';


--
-- Name: v2_stat_server_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_stat_server_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_stat_server_id_seq OWNER TO tanxuan;

--
-- Name: v2_stat_server_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_stat_server_id_seq OWNED BY public.v2_stat_server.id;


--
-- Name: v2_stat_user; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_stat_user (
    id integer NOT NULL,
    user_id integer NOT NULL,
    server_rate numeric(10,2) NOT NULL,
    u bigint NOT NULL,
    d bigint NOT NULL,
    record_type character(2) NOT NULL,
    record_at integer NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_stat_user OWNER TO tanxuan;

--
-- Name: v2_stat_user_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_stat_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_stat_user_id_seq OWNER TO tanxuan;

--
-- Name: v2_stat_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_stat_user_id_seq OWNED BY public.v2_stat_user.id;


--
-- Name: v2_ticket; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_ticket (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subject character varying(255) NOT NULL,
    level integer NOT NULL,
    status integer DEFAULT 0 NOT NULL,
    reply_status integer DEFAULT 1 NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_ticket OWNER TO tanxuan;

--
-- Name: COLUMN v2_ticket.status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_ticket.status IS '0:已开启 1:已关闭';


--
-- Name: COLUMN v2_ticket.reply_status; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_ticket.reply_status IS '0:待回复 1:已回复';


--
-- Name: v2_ticket_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_ticket_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_ticket_id_seq OWNER TO tanxuan;

--
-- Name: v2_ticket_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_ticket_id_seq OWNED BY public.v2_ticket.id;


--
-- Name: v2_ticket_message; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_ticket_message (
    id integer NOT NULL,
    user_id integer NOT NULL,
    ticket_id integer NOT NULL,
    message text NOT NULL,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
);


ALTER TABLE public.v2_ticket_message OWNER TO tanxuan;

--
-- Name: v2_ticket_message_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_ticket_message_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_ticket_message_id_seq OWNER TO tanxuan;

--
-- Name: v2_ticket_message_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_ticket_message_id_seq OWNED BY public.v2_ticket_message.id;


--
-- Name: v2_traffic_reset_logs; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_traffic_reset_logs (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    reset_type character varying(50) NOT NULL,
    reset_time timestamp(0) without time zone NOT NULL,
    old_upload bigint DEFAULT '0'::bigint NOT NULL,
    old_download bigint DEFAULT '0'::bigint NOT NULL,
    old_total bigint DEFAULT '0'::bigint NOT NULL,
    new_upload bigint DEFAULT '0'::bigint NOT NULL,
    new_download bigint DEFAULT '0'::bigint NOT NULL,
    new_total bigint DEFAULT '0'::bigint NOT NULL,
    trigger_source character varying(50) NOT NULL,
    metadata json,
    created_at timestamp(0) without time zone,
    updated_at timestamp(0) without time zone
);


ALTER TABLE public.v2_traffic_reset_logs OWNER TO tanxuan;

--
-- Name: COLUMN v2_traffic_reset_logs.user_id; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.user_id IS '用户ID';


--
-- Name: COLUMN v2_traffic_reset_logs.reset_type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.reset_type IS '重置类型';


--
-- Name: COLUMN v2_traffic_reset_logs.reset_time; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.reset_time IS '重置时间';


--
-- Name: COLUMN v2_traffic_reset_logs.old_upload; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.old_upload IS '重置前上传流量';


--
-- Name: COLUMN v2_traffic_reset_logs.old_download; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.old_download IS '重置前下载流量';


--
-- Name: COLUMN v2_traffic_reset_logs.old_total; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.old_total IS '重置前总流量';


--
-- Name: COLUMN v2_traffic_reset_logs.new_upload; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.new_upload IS '重置后上传流量';


--
-- Name: COLUMN v2_traffic_reset_logs.new_download; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.new_download IS '重置后下载流量';


--
-- Name: COLUMN v2_traffic_reset_logs.new_total; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.new_total IS '重置后总流量';


--
-- Name: COLUMN v2_traffic_reset_logs.trigger_source; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.trigger_source IS '触发来源';


--
-- Name: COLUMN v2_traffic_reset_logs.metadata; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_traffic_reset_logs.metadata IS '额外元数据';


--
-- Name: v2_traffic_reset_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_traffic_reset_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_traffic_reset_logs_id_seq OWNER TO tanxuan;

--
-- Name: v2_traffic_reset_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_traffic_reset_logs_id_seq OWNED BY public.v2_traffic_reset_logs.id;


--
-- Name: v2_user; Type: TABLE; Schema: public; Owner: tanxuan
--

CREATE TABLE public.v2_user (
    id integer NOT NULL,
    invite_user_id integer,
    telegram_id bigint,
    email character varying(64) NOT NULL,
    password character varying(64) NOT NULL,
    password_algo character(10),
    password_salt character(10),
    balance integer DEFAULT 0 NOT NULL,
    discount integer,
    commission_type smallint DEFAULT '0'::smallint NOT NULL,
    commission_rate integer,
    commission_balance integer DEFAULT 0 NOT NULL,
    t integer DEFAULT 0 NOT NULL,
    u bigint DEFAULT '0'::bigint NOT NULL,
    d bigint DEFAULT '0'::bigint NOT NULL,
    transfer_enable bigint DEFAULT '0'::bigint NOT NULL,
    banned boolean DEFAULT false NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    last_login_at integer,
    is_staff boolean DEFAULT false NOT NULL,
    last_login_ip integer,
    uuid character varying(36) NOT NULL,
    group_id integer,
    plan_id integer,
    speed_limit integer,
    remind_expire smallint DEFAULT '1'::smallint,
    remind_traffic smallint DEFAULT '1'::smallint,
    token character varying(64) NOT NULL,
    expired_at bigint DEFAULT '0'::bigint,
    remarks text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL,
    device_limit integer,
    online_count integer,
    last_online_at timestamp(0) without time zone,
    next_reset_at integer,
    last_reset_at integer,
    reset_count integer DEFAULT 0 NOT NULL,
    is_super_admin boolean DEFAULT false NOT NULL
);


ALTER TABLE public.v2_user OWNER TO tanxuan;

--
-- Name: COLUMN v2_user.commission_type; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_user.commission_type IS '0: system 1: period 2: onetime';


--
-- Name: COLUMN v2_user.next_reset_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_user.next_reset_at IS '下次流量重置时间';


--
-- Name: COLUMN v2_user.last_reset_at; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_user.last_reset_at IS '上次流量重置时间';


--
-- Name: COLUMN v2_user.reset_count; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_user.reset_count IS '流量重置次数';


--
-- Name: COLUMN v2_user.is_super_admin; Type: COMMENT; Schema: public; Owner: tanxuan
--

COMMENT ON COLUMN public.v2_user.is_super_admin IS '是否超级管理员';


--
-- Name: v2_user_id_seq; Type: SEQUENCE; Schema: public; Owner: tanxuan
--

CREATE SEQUENCE public.v2_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.v2_user_id_seq OWNER TO tanxuan;

--
-- Name: v2_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tanxuan
--

ALTER SEQUENCE public.v2_user_id_seq OWNED BY public.v2_user.id;


--
-- Name: failed_jobs id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.failed_jobs ALTER COLUMN id SET DEFAULT nextval('public.failed_jobs_id_seq'::regclass);


--
-- Name: migrations id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.migrations ALTER COLUMN id SET DEFAULT nextval('public.migrations_id_seq'::regclass);


--
-- Name: personal_access_tokens id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.personal_access_tokens ALTER COLUMN id SET DEFAULT nextval('public.personal_access_tokens_id_seq'::regclass);


--
-- Name: v2_commission_log id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_commission_log ALTER COLUMN id SET DEFAULT nextval('public.v2_commission_log_id_seq'::regclass);


--
-- Name: v2_coupon id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_coupon ALTER COLUMN id SET DEFAULT nextval('public.v2_coupon_id_seq'::regclass);


--
-- Name: v2_gift_card_code id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_code ALTER COLUMN id SET DEFAULT nextval('public.v2_gift_card_code_id_seq'::regclass);


--
-- Name: v2_gift_card_template id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_template ALTER COLUMN id SET DEFAULT nextval('public.v2_gift_card_template_id_seq'::regclass);


--
-- Name: v2_gift_card_usage id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_usage ALTER COLUMN id SET DEFAULT nextval('public.v2_gift_card_usage_id_seq'::regclass);


--
-- Name: v2_invite_code id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_invite_code ALTER COLUMN id SET DEFAULT nextval('public.v2_invite_code_id_seq'::regclass);


--
-- Name: v2_knowledge id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_knowledge ALTER COLUMN id SET DEFAULT nextval('public.v2_knowledge_id_seq'::regclass);


--
-- Name: v2_log id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_log ALTER COLUMN id SET DEFAULT nextval('public.v2_log_id_seq'::regclass);


--
-- Name: v2_mail_log id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_mail_log ALTER COLUMN id SET DEFAULT nextval('public.v2_mail_log_id_seq'::regclass);


--
-- Name: v2_notice id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_notice ALTER COLUMN id SET DEFAULT nextval('public.v2_notice_id_seq'::regclass);


--
-- Name: v2_order id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_order ALTER COLUMN id SET DEFAULT nextval('public.v2_order_id_seq'::regclass);


--
-- Name: v2_payment id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_payment ALTER COLUMN id SET DEFAULT nextval('public.v2_payment_id_seq'::regclass);


--
-- Name: v2_payment_callback_logs id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_payment_callback_logs ALTER COLUMN id SET DEFAULT nextval('public.v2_payment_callback_logs_id_seq'::regclass);


--
-- Name: v2_plan id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_plan ALTER COLUMN id SET DEFAULT nextval('public.v2_plan_id_seq'::regclass);


--
-- Name: v2_plugins id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_plugins ALTER COLUMN id SET DEFAULT nextval('public.v2_plugins_id_seq'::regclass);


--
-- Name: v2_server id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server ALTER COLUMN id SET DEFAULT nextval('public.v2_server_id_seq'::regclass);


--
-- Name: v2_server_group id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server_group ALTER COLUMN id SET DEFAULT nextval('public.v2_server_group_id_seq'::regclass);


--
-- Name: v2_server_route id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server_route ALTER COLUMN id SET DEFAULT nextval('public.v2_server_route_id_seq'::regclass);


--
-- Name: v2_settings id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_settings ALTER COLUMN id SET DEFAULT nextval('public.v2_settings_id_seq'::regclass);


--
-- Name: v2_stat id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat ALTER COLUMN id SET DEFAULT nextval('public.v2_stat_id_seq'::regclass);


--
-- Name: v2_stat_server id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_server ALTER COLUMN id SET DEFAULT nextval('public.v2_stat_server_id_seq'::regclass);


--
-- Name: v2_stat_user id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_user ALTER COLUMN id SET DEFAULT nextval('public.v2_stat_user_id_seq'::regclass);


--
-- Name: v2_ticket id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_ticket ALTER COLUMN id SET DEFAULT nextval('public.v2_ticket_id_seq'::regclass);


--
-- Name: v2_ticket_message id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_ticket_message ALTER COLUMN id SET DEFAULT nextval('public.v2_ticket_message_id_seq'::regclass);


--
-- Name: v2_traffic_reset_logs id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_traffic_reset_logs ALTER COLUMN id SET DEFAULT nextval('public.v2_traffic_reset_logs_id_seq'::regclass);


--
-- Name: v2_user id; Type: DEFAULT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_user ALTER COLUMN id SET DEFAULT nextval('public.v2_user_id_seq'::regclass);


--
-- Name: v2_user email; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_user
    ADD CONSTRAINT email UNIQUE (email);


--
-- Name: failed_jobs failed_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.failed_jobs
    ADD CONSTRAINT failed_jobs_pkey PRIMARY KEY (id);


--
-- Name: migrations migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.migrations
    ADD CONSTRAINT migrations_pkey PRIMARY KEY (id);


--
-- Name: personal_access_tokens personal_access_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.personal_access_tokens
    ADD CONSTRAINT personal_access_tokens_pkey PRIMARY KEY (id);


--
-- Name: personal_access_tokens personal_access_tokens_token_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.personal_access_tokens
    ADD CONSTRAINT personal_access_tokens_token_unique UNIQUE (token);


--
-- Name: v2_stat_server server_id_server_type_record_at; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_server
    ADD CONSTRAINT server_id_server_type_record_at UNIQUE (server_id, server_type, record_at);


--
-- Name: v2_stat_user server_rate_user_id_record_at; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_user
    ADD CONSTRAINT server_rate_user_id_record_at UNIQUE (server_rate, user_id, record_at);


--
-- Name: v2_order trade_no; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_order
    ADD CONSTRAINT trade_no UNIQUE (trade_no);


--
-- Name: v2_commission_log v2_commission_log_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_commission_log
    ADD CONSTRAINT v2_commission_log_pkey PRIMARY KEY (id);


--
-- Name: v2_coupon v2_coupon_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_coupon
    ADD CONSTRAINT v2_coupon_pkey PRIMARY KEY (id);


--
-- Name: v2_gift_card_code v2_gift_card_code_code_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_code
    ADD CONSTRAINT v2_gift_card_code_code_unique UNIQUE (code);


--
-- Name: v2_gift_card_code v2_gift_card_code_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_code
    ADD CONSTRAINT v2_gift_card_code_pkey PRIMARY KEY (id);


--
-- Name: v2_gift_card_template v2_gift_card_template_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_template
    ADD CONSTRAINT v2_gift_card_template_pkey PRIMARY KEY (id);


--
-- Name: v2_gift_card_usage v2_gift_card_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_gift_card_usage
    ADD CONSTRAINT v2_gift_card_usage_pkey PRIMARY KEY (id);


--
-- Name: v2_invite_code v2_invite_code_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_invite_code
    ADD CONSTRAINT v2_invite_code_pkey PRIMARY KEY (id);


--
-- Name: v2_knowledge v2_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_knowledge
    ADD CONSTRAINT v2_knowledge_pkey PRIMARY KEY (id);


--
-- Name: v2_log v2_log_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_log
    ADD CONSTRAINT v2_log_pkey PRIMARY KEY (id);


--
-- Name: v2_mail_log v2_mail_log_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_mail_log
    ADD CONSTRAINT v2_mail_log_pkey PRIMARY KEY (id);


--
-- Name: v2_notice v2_notice_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_notice
    ADD CONSTRAINT v2_notice_pkey PRIMARY KEY (id);


--
-- Name: v2_order v2_order_callback_no_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_order
    ADD CONSTRAINT v2_order_callback_no_unique UNIQUE (callback_no);


--
-- Name: v2_order v2_order_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_order
    ADD CONSTRAINT v2_order_pkey PRIMARY KEY (id);


--
-- Name: v2_payment_callback_logs v2_payment_callback_logs_callback_no_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_payment_callback_logs
    ADD CONSTRAINT v2_payment_callback_logs_callback_no_unique UNIQUE (callback_no);


--
-- Name: v2_payment_callback_logs v2_payment_callback_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_payment_callback_logs
    ADD CONSTRAINT v2_payment_callback_logs_pkey PRIMARY KEY (id);


--
-- Name: v2_payment v2_payment_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_payment
    ADD CONSTRAINT v2_payment_pkey PRIMARY KEY (id);


--
-- Name: v2_plan v2_plan_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_plan
    ADD CONSTRAINT v2_plan_pkey PRIMARY KEY (id);


--
-- Name: v2_plugins v2_plugins_code_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_plugins
    ADD CONSTRAINT v2_plugins_code_unique UNIQUE (code);


--
-- Name: v2_plugins v2_plugins_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_plugins
    ADD CONSTRAINT v2_plugins_pkey PRIMARY KEY (id);


--
-- Name: v2_server_group v2_server_group_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server_group
    ADD CONSTRAINT v2_server_group_pkey PRIMARY KEY (id);


--
-- Name: v2_server v2_server_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server
    ADD CONSTRAINT v2_server_pkey PRIMARY KEY (id);


--
-- Name: v2_server_route v2_server_route_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server_route
    ADD CONSTRAINT v2_server_route_pkey PRIMARY KEY (id);


--
-- Name: v2_server v2_server_type_code_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_server
    ADD CONSTRAINT v2_server_type_code_unique UNIQUE (type, code);


--
-- Name: v2_settings v2_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_settings
    ADD CONSTRAINT v2_settings_pkey PRIMARY KEY (id);


--
-- Name: v2_stat v2_stat_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat
    ADD CONSTRAINT v2_stat_pkey PRIMARY KEY (id);


--
-- Name: v2_stat v2_stat_record_at_unique; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat
    ADD CONSTRAINT v2_stat_record_at_unique UNIQUE (record_at);


--
-- Name: v2_stat_server v2_stat_server_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_server
    ADD CONSTRAINT v2_stat_server_pkey PRIMARY KEY (id);


--
-- Name: v2_stat_user v2_stat_user_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_stat_user
    ADD CONSTRAINT v2_stat_user_pkey PRIMARY KEY (id);


--
-- Name: v2_ticket_message v2_ticket_message_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_ticket_message
    ADD CONSTRAINT v2_ticket_message_pkey PRIMARY KEY (id);


--
-- Name: v2_ticket v2_ticket_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_ticket
    ADD CONSTRAINT v2_ticket_pkey PRIMARY KEY (id);


--
-- Name: v2_traffic_reset_logs v2_traffic_reset_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_traffic_reset_logs
    ADD CONSTRAINT v2_traffic_reset_logs_pkey PRIMARY KEY (id);


--
-- Name: v2_user v2_user_pkey; Type: CONSTRAINT; Schema: public; Owner: tanxuan
--

ALTER TABLE ONLY public.v2_user
    ADD CONSTRAINT v2_user_pkey PRIMARY KEY (id);


--
-- Name: idx_gift_code_batch_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_batch_id ON public.v2_gift_card_code USING btree (batch_id);


--
-- Name: idx_gift_code_expires_at; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_expires_at ON public.v2_gift_card_code USING btree (expires_at);


--
-- Name: idx_gift_code_lookup; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_lookup ON public.v2_gift_card_code USING btree (code, status, expires_at);


--
-- Name: idx_gift_code_status; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_status ON public.v2_gift_card_code USING btree (status);


--
-- Name: idx_gift_code_template_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_template_id ON public.v2_gift_card_code USING btree (template_id);


--
-- Name: idx_gift_code_user_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_code_user_id ON public.v2_gift_card_code USING btree (user_id);


--
-- Name: idx_gift_template_created_at; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_template_created_at ON public.v2_gift_card_template USING btree (created_at);


--
-- Name: idx_gift_template_type_status; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_template_type_status ON public.v2_gift_card_template USING btree (type, status);


--
-- Name: idx_gift_usage_code_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_code_id ON public.v2_gift_card_usage USING btree (code_id);


--
-- Name: idx_gift_usage_created_at; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_created_at ON public.v2_gift_card_usage USING btree (created_at);


--
-- Name: idx_gift_usage_invite_user_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_invite_user_id ON public.v2_gift_card_usage USING btree (invite_user_id);


--
-- Name: idx_gift_usage_template_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_template_id ON public.v2_gift_card_usage USING btree (template_id);


--
-- Name: idx_gift_usage_template_stats; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_template_stats ON public.v2_gift_card_usage USING btree (template_id, created_at);


--
-- Name: idx_gift_usage_user_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_user_id ON public.v2_gift_card_usage USING btree (user_id);


--
-- Name: idx_gift_usage_user_usage; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_gift_usage_user_usage ON public.v2_gift_card_usage USING btree (user_id, created_at);


--
-- Name: idx_next_reset_at; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_next_reset_at ON public.v2_user USING btree (next_reset_at);


--
-- Name: idx_reset_time; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_reset_time ON public.v2_traffic_reset_logs USING btree (reset_time);


--
-- Name: idx_setting_name; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_setting_name ON public.v2_settings USING btree (name);


--
-- Name: idx_user_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_user_id ON public.v2_traffic_reset_logs USING btree (user_id);


--
-- Name: idx_user_reset_time; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX idx_user_reset_time ON public.v2_traffic_reset_logs USING btree (user_id, reset_time);


--
-- Name: personal_access_tokens_tokenable_type_tokenable_id_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX personal_access_tokens_tokenable_type_tokenable_id_index ON public.personal_access_tokens USING btree (tokenable_type, tokenable_id);


--
-- Name: record_at; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX record_at ON public.v2_stat_server USING btree (record_at);


--
-- Name: server_id; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX server_id ON public.v2_stat_server USING btree (server_id);


--
-- Name: v2_commission_log_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_commission_log_created_at_index ON public.v2_commission_log USING btree (created_at);


--
-- Name: v2_commission_log_get_amount_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_commission_log_get_amount_index ON public.v2_commission_log USING btree (get_amount);


--
-- Name: v2_notice_sort_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_notice_sort_index ON public.v2_notice USING btree (sort);


--
-- Name: v2_order_commission_balance_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_commission_balance_index ON public.v2_order USING btree (commission_balance);


--
-- Name: v2_order_commission_status_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_commission_status_index ON public.v2_order USING btree (commission_status);


--
-- Name: v2_order_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_created_at_index ON public.v2_order USING btree (created_at);


--
-- Name: v2_order_invite_user_id_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_invite_user_id_index ON public.v2_order USING btree (invite_user_id);


--
-- Name: v2_order_status_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_status_index ON public.v2_order USING btree (status);


--
-- Name: v2_order_total_amount_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_total_amount_index ON public.v2_order USING btree (total_amount);


--
-- Name: v2_order_updated_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_order_updated_at_index ON public.v2_order USING btree (updated_at);


--
-- Name: v2_payment_callback_logs_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_payment_callback_logs_created_at_index ON public.v2_payment_callback_logs USING btree (created_at);


--
-- Name: v2_payment_callback_logs_payment_method_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_payment_callback_logs_payment_method_created_at_index ON public.v2_payment_callback_logs USING btree (payment_method, created_at);


--
-- Name: v2_payment_callback_logs_trade_no_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_payment_callback_logs_trade_no_index ON public.v2_payment_callback_logs USING btree (trade_no);


--
-- Name: v2_plugins_type_is_enabled_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_plugins_type_is_enabled_index ON public.v2_plugins USING btree (type, is_enabled);


--
-- Name: v2_server_sort_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_server_sort_index ON public.v2_server USING btree (sort);


--
-- Name: v2_stat_server_d_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_server_d_index ON public.v2_stat_server USING btree (d);


--
-- Name: v2_stat_server_record_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_server_record_at_index ON public.v2_stat_server USING btree (record_at);


--
-- Name: v2_stat_server_server_id_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_server_server_id_index ON public.v2_stat_server USING btree (server_id);


--
-- Name: v2_stat_server_u_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_server_u_index ON public.v2_stat_server USING btree (u);


--
-- Name: v2_stat_user_d_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_user_d_index ON public.v2_stat_user USING btree (d);


--
-- Name: v2_stat_user_u_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_user_u_index ON public.v2_stat_user USING btree (u);


--
-- Name: v2_stat_user_user_id_server_rate_record_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_stat_user_user_id_server_rate_record_at_index ON public.v2_stat_user USING btree (user_id, server_rate, record_at);


--
-- Name: v2_ticket_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_ticket_created_at_index ON public.v2_ticket USING btree (created_at);


--
-- Name: v2_ticket_status_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_ticket_status_index ON public.v2_ticket USING btree (status);


--
-- Name: v2_user_created_at_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_user_created_at_index ON public.v2_user USING btree (created_at);


--
-- Name: v2_user_online_count_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_user_online_count_index ON public.v2_user USING btree (online_count);


--
-- Name: v2_user_t_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_user_t_index ON public.v2_user USING btree (t);


--
-- Name: v2_user_u_d_expired_at_group_id_banned_transfer_enable_index; Type: INDEX; Schema: public; Owner: tanxuan
--

CREATE INDEX v2_user_u_d_expired_at_group_id_banned_transfer_enable_index ON public.v2_user USING btree (u, d, expired_at, group_id, banned, transfer_enable);


--
-- PostgreSQL database dump complete
--

\unrestrict ntTF5yb9S4Z2SJZfPXiKoAhvVZOom9LsLjpjNZia7xmzMhCo5YpomBRWW4UvNB8

