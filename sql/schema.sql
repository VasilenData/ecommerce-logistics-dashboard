-- Raw tables (one per Olist CSV). Types are explicit so bad data fails loudly at load time.
DROP TABLE IF EXISTS order_reviews, order_payments, order_items, orders, customers, products, sellers, category_translation CASCADE;

CREATE TABLE customers (customer_id TEXT PRIMARY KEY, customer_unique_id TEXT NOT NULL,
  customer_zip_code_prefix TEXT, customer_city TEXT, customer_state CHAR(2));
CREATE TABLE sellers (seller_id TEXT PRIMARY KEY, seller_zip_code_prefix TEXT, seller_city TEXT, seller_state CHAR(2));
CREATE TABLE category_translation (product_category_name TEXT PRIMARY KEY, product_category_name_english TEXT);
CREATE TABLE products (product_id TEXT PRIMARY KEY, product_category_name TEXT,
  product_name_lenght INT, product_description_lenght INT, product_photos_qty INT,
  product_weight_g INT, product_length_cm INT, product_height_cm INT, product_width_cm INT);
CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
  order_status TEXT NOT NULL, order_purchase_timestamp TIMESTAMP NOT NULL, order_approved_at TIMESTAMP,
  order_delivered_carrier_date TIMESTAMP, order_delivered_customer_date TIMESTAMP, order_estimated_delivery_date TIMESTAMP);
CREATE TABLE order_items (order_id TEXT NOT NULL REFERENCES orders, order_item_id INT NOT NULL,
  product_id TEXT NOT NULL, seller_id TEXT NOT NULL, shipping_limit_date TIMESTAMP,
  price NUMERIC(10,2) NOT NULL, freight_value NUMERIC(10,2) NOT NULL, PRIMARY KEY (order_id, order_item_id));
CREATE TABLE order_payments (order_id TEXT NOT NULL REFERENCES orders, payment_sequential INT NOT NULL,
  payment_type TEXT, payment_installments INT, payment_value NUMERIC(10,2), PRIMARY KEY (order_id, payment_sequential));
CREATE TABLE order_reviews (review_id TEXT, order_id TEXT NOT NULL, review_score INT,
  review_comment_title TEXT, review_comment_message TEXT, review_creation_date TIMESTAMP, review_answer_timestamp TIMESTAMP);

CREATE INDEX ON order_items (product_id); CREATE INDEX ON order_items (seller_id);
CREATE INDEX ON orders (customer_id); CREATE INDEX ON order_reviews (order_id);
